use serde::Serialize;
use serde_json::{json, Value};
use std::{
    collections::VecDeque,
    io::{BufRead, BufReader, Read, Write},
    net::IpAddr,
    path::PathBuf,
    process::{Command, Stdio},
    sync::{Arc, Mutex},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{Manager, State};
mod ble;
pub mod target;
mod shared;
pub mod agent;
mod diagnostics;
pub mod node_update;
use std::sync::atomic::AtomicBool;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

pub const NODE_RPC_METHODS:&[&str]=&["get_status","get_config","get_probe_transport","probe.exchange","probe.stream.open","probe.stream.read","probe.stream.write","probe.stream.close","probe.stream.abort","probe.files.status","probe.files.begin","probe.files.write","probe.files.commit","probe.files.abort","probe.metrics.reset","probe.metrics.snapshot","firmware.status","firmware.begin","firmware.write","firmware.finish","firmware.claim","firmware.activate","firmware.confirm","firmware.abort","get_logs","scan_wifi","set_config","connect_wifi","apply_network","pair","control.acquire","control.renew","control.release"];

pub enum Link {
    Serial { port: Box<dyn serialport::SerialPort>, pending: Vec<u8> },
    Lan { url: String, token: String },
    Ble(ble::Link),
}
pub struct Service {
    link: Mutex<Option<Link>>,
    shared: Mutex<Option<shared::Client>>,
    logs: Mutex<VecDeque<String>>,
    diagnostics: Mutex<diagnostics::Store>,
    preferences: Mutex<Value>,
    link_revision: std::sync::atomic::AtomicU64,
    pub job: Mutex<Job>,
    pub target: Mutex<target::TargetJob>,
    target_stop: AtomicBool,
    operation_gate: Mutex<()>,
}
#[derive(Clone, Default, Serialize)]
pub struct Job {
    pub running: bool,
    pub stage: String,
    pub done: u64,
    pub total: u64,
    pub error: String,
    pub backup_path: String,
    pub detail: String,
}
impl Default for Service {
    fn default() -> Self {
        Self {
            link: Mutex::new(None),
            shared: Mutex::new(None),
            logs: Mutex::new(VecDeque::new()),
            diagnostics: Mutex::new(diagnostics::Store::default()),
            preferences: Mutex::new(agent::load_preferences()),
            link_revision: std::sync::atomic::AtomicU64::new(0),
            job: Mutex::new(Job::default()),
            target: Mutex::new(target::TargetJob::default()),
            target_stop: AtomicBool::new(false),
            operation_gate: Mutex::new(()),
        }
    }
}
impl Service {
    fn log(&self, text: &str) {
        self.log_from("device",text);
    }
    fn log_from(&self, source:&str, text: &str) {
        let severity=diagnostics::level(text);
        let text=diagnostics::redact(text);
        self.diagnostics.lock().unwrap().push(severity,source,&text);
        let mut logs = self.logs.lock().unwrap();
        logs.push_back(text.chars().take(1000).collect());
        while logs.len() > 1000 {
            logs.pop_front();
        }
    }
    fn collect_backend_logs(&self){
        if let Ok(mut shared)=self.shared.try_lock(){
            if let Some(client)=shared.as_mut(){
                if let Ok(data)=client.call("diagnostics",json!({})){
                    if let Some(lines)=data["lines"].as_array(){for line in lines.iter().filter_map(Value::as_str){
                        self.log_from("backend",line);
                    }}
                }
            }
        }
    }
    pub fn connect_serial(&self, port: &str) -> Result<(), String> {
        let _gate = self.operation_gate.lock().unwrap();
        if self.shared.lock().unwrap().is_some() { return Err("共享调试已接管连接，请先退出共享客户端".into()); }
        if self.target.lock().unwrap().running { return Err("目标操作正在运行，请等待结束".into()); }
        if self.job.lock().unwrap().running {
            return Err("正在安装固件，请等待完成".into());
        }
        let mut link = self.link.lock().unwrap();
        *link = None;
        let mut p = serialport::new(port, 115200)
            .timeout(Duration::from_millis(100))
            .dtr_on_open(false)
            .open()
            .map_err(|e| format!("无法打开 {port}：{e}"))?;
        p.write_data_terminal_ready(false)
            .map_err(|e| e.to_string())?;
        p.write_request_to_send(false).map_err(|e| e.to_string())?;
        *link = Some(Link::Serial { port:p, pending:Vec::new() });
        self.link_revision.fetch_add(1,std::sync::atomic::Ordering::Relaxed);
        self.log(&format!("已连接串口 {port} · 115200"));
        Ok(())
    }
    pub fn rpc(&self, method: &str, params: Value) -> Result<Value, String> {
        if !NODE_RPC_METHODS.contains(&method)
        {
            return Err("不支持的配置命令".into());
        }
        let request =
            json!({"v":1,"id":uuid::Uuid::new_v4().to_string(),"method":method,"params":params});
        let id = request["id"].as_str().unwrap();
        let mut link = self.link.lock().unwrap();
        let link = link.as_mut().ok_or("尚未连接设备")?;
        let reply = match link {
            Link::Ble(connection) => connection.rpc(request.clone())?,
            Link::Lan { url, token } => {
                let response = reqwest::blocking::Client::builder()
                    .timeout(Duration::from_secs(25))
                    .no_proxy()
                    .build()
                    .map_err(|e| e.to_string())?
                    .post(format!("{}/api/v1/rpc", url.trim_end_matches('/')))
                    .bearer_auth(token)
                    .json(&request)
                    .send()
                    .map_err(|_| "局域网请求失败或超时；写入结果请重新读取核对".to_string())?;
                if !response.status().is_success() {
                    return Err(format!("设备 HTTP 错误：{}", response.status()));
                }
                let mut bytes = Vec::new();
                response
                    .take(65537)
                    .read_to_end(&mut bytes)
                    .map_err(|e| e.to_string())?;
                if bytes.len() > 65536 {
                    return Err("设备响应超过限制".into());
                }
                serde_json::from_slice::<Value>(&bytes)
                    .map_err(|_| "设备返回无效 JSON".to_string())?
            }
            Link::Serial { port, pending } => {
                let data = format!("@MKCFG {}\n", request);
                if data.len() > 4096 {
                    return Err("配置请求过长".into());
                }
                port.write_all(data.as_bytes()).map_err(|e| e.to_string())?;
                let deadline = Instant::now()
                    + Duration::from_secs(if method == "scan_wifi" { 25 } else { 6 });
                let mut chunk = [0u8; 2048];
                loop {
                    if Instant::now() > deadline {
                        return Err("设备未响应配置协议；出厂固件可使用「安装默认固件」。写入超时请先重新读取核对".into());
                    }
                    if let Some(value) = drain_serial_reply(pending, id, |text| self.log(text)) { break value; }
                    let available = port.bytes_to_read().map_err(|e|format!("串口接收状态失败：{e}"))? as usize;
                    let size = available.clamp(1, chunk.len());
                    match port.read(&mut chunk[..size]) {
                        Ok(n) => {
                            pending.extend_from_slice(&chunk[..n]);
                            if pending.len()>65536 { pending.clear(); return Err("串口响应超过限制；不会重发请求".into()); }
                        }
                        Err(e) if e.kind() == std::io::ErrorKind::TimedOut => {}
                        Err(e) => return Err(format!("串口已断开：{e}")),
                    }
                }
            }
        };
        if reply["v"] != 1 || reply["id"].as_str() != Some(id) {
            return Err("配置协议版本或响应标识不匹配".into());
        }
        if reply["ok"] != true {
            return Err(reply["error"]["message"]
                .as_str()
                .unwrap_or("设备拒绝请求")
                .to_string());
        }
        if method == "get_logs" {
            if let Some(lines) = reply["data"].as_array() {
                for line in lines {
                    if let Some(line) = line.as_str() {
                        let exists = self.logs.lock().unwrap().iter().any(|v| v == line);
                        if !exists {
                            self.log(line);
                        }
                    }
                }
            }
        }
        Ok(reply["data"].clone())
    }
}
fn drain_serial_reply(pending: &mut Vec<u8>, id: &str, mut log: impl FnMut(&str)) -> Option<Value> {
    while let Some(end) = pending.iter().position(|b|*b==b'\n') {
        let bytes:Vec<u8> = pending.drain(..=end).collect();
        let text = String::from_utf8_lossy(&bytes);
        let text = text.trim();
        if let Some((_,payload)) = text.split_once("@MKCFG ") {
            if let Ok(value) = serde_json::from_str::<Value>(payload) {
                if value["id"].as_str()==Some(id) { return Some(value); }
            }
            // Never log an unmatched credential-bearing configuration reply.
        } else if !text.is_empty() { log(text); }
    }
    None
}
impl Service {
    pub fn connect_lan(&self, url: String, token: String) -> Result<(), String> {
        let _gate = self.operation_gate.lock().unwrap();
        if self.shared.lock().unwrap().is_some() { return Err("共享调试已接管连接，请先退出共享客户端".into()); }
        if self.job.lock().unwrap().running || self.target.lock().unwrap().running { return Err("设备任务正在运行".into()); }
        let url = validate_lan(&url)?;
        if token.len()!=32 || !token.bytes().all(|b| b.is_ascii_hexdigit()) { return Err("请输入32位管理密钥".into()); }
        *self.link.lock().unwrap() = Some(Link::Lan { url, token });
        self.link_revision.fetch_add(1,std::sync::atomic::Ordering::Relaxed);
        Ok(())
    }
    pub fn disconnect(&self) -> Result<(), String> {
        let _gate = self.operation_gate.lock().unwrap();
        if self.job.lock().unwrap().running || self.target.lock().unwrap().running { return Err("设备任务正在运行，请等待完成或停止采集".into()); }
        *self.link.lock().unwrap() = None;
        Ok(())
    }
    pub fn connect_ble(&self, address: String, token: String) -> Result<(), String> {
        let _gate = self.operation_gate.lock().unwrap();
        if self.shared.lock().unwrap().is_some() { return Err("共享调试已接管连接，请先退出共享客户端".into()); }
        if self.target.lock().unwrap().running { return Err("目标操作正在运行，请等待结束".into()); }
        if self.job.lock().unwrap().running {
            return Err("正在安装固件".into());
        }
        let mut link = self.link.lock().unwrap();
        *link = None;
        *link = Some(Link::Ble(ble::Link::open(address, token)?));
        self.link_revision.fetch_add(1,std::sync::atomic::Ordering::Relaxed);
        self.log("BLE加密配置会话已建立");
        Ok(())
    }
}
#[tauri::command]
async fn list_ble() -> Result<Vec<ble::Device>, String> {
    tauri::async_runtime::spawn_blocking(ble::list)
        .await
        .map_err(|e| e.to_string())?
}
#[tauri::command]
async fn connect_ble(
    state: State<'_, AppState>,
    address: String,
    token: String,
) -> Result<(), String> {
    let service = state.service.clone();
    tauri::async_runtime::spawn_blocking(move || service.connect_ble(address, token))
        .await
        .map_err(|e| e.to_string())?
}
struct AppState {
    service: Arc<Service>,
}
#[tauri::command]
fn list_ports() -> Result<Value, String> {
    let ports = serialport::available_ports().map_err(|e| e.to_string())?;
    Ok(Value::Array(
        ports
            .into_iter()
            .map(|p| {
                let mut v = json!({"name":p.port_name,"description":"串口设备"});
                if let serialport::SerialPortType::UsbPort(info) = p.port_type {
                    v["description"] = json!(info.product.unwrap_or_else(|| "USB 串口".into()));
                    v["vid"] = json!(info.vid);
                    v["pid"] = json!(info.pid);
                }
                v
            })
            .collect(),
    ))
}
#[tauri::command]
async fn connect_serial(state: State<'_, AppState>, port: String) -> Result<(), String> {
    let s = state.service.clone();
    tauri::async_runtime::spawn_blocking(move || s.connect_serial(&port))
        .await
        .map_err(|e| e.to_string())?
}
fn validate_lan(url: &str) -> Result<String, String> {
    let parsed =
        reqwest::Url::parse(url).map_err(|_| "请输入完整的局域网 HTTP 地址".to_string())?;
    if parsed.scheme() != "http"
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || !matches!(parsed.path(), "" | "/")
        || parsed.query().is_some()
        || parsed.fragment().is_some()
    {
        return Err("请输入设备的 http://设备局域网IP 地址".into());
    }
    let ip: IpAddr = parsed
        .host_str()
        .ok_or("缺少设备 IP")?
        .parse()
        .map_err(|_| "请使用设备报告的局域网 IP".to_string())?;
    let local = match ip {
        IpAddr::V4(v) => v.is_private() || v.is_loopback() || v.is_link_local(),
        IpAddr::V6(v) => v.is_loopback() || v.is_unique_local() || v.is_unicast_link_local(),
    };
    if !local {
        return Err("管理连接只支持局域网地址".into());
    }
    Ok(url.trim_end_matches('/').to_string())
}
#[tauri::command]
async fn connect_lan(state: State<'_, AppState>, url: String, token: String) -> Result<(), String> {
    let service = state.service.clone();
    tauri::async_runtime::spawn_blocking(move || service.connect_lan(url, token))
    .await
    .map_err(|e| e.to_string())?
}
#[tauri::command]
async fn disconnect(state: State<'_, AppState>) -> Result<(), String> {
    let s = state.service.clone();
    tauri::async_runtime::spawn_blocking(move || s.disconnect())
    .await
    .map_err(|e| e.to_string())?
}
#[tauri::command]
async fn rpc(state: State<'_, AppState>, method: String, params: Value) -> Result<Value, String> {
    let s = state.service.clone();
    tauri::async_runtime::spawn_blocking(move || s.rpc(&method, params))
        .await
        .map_err(|e| e.to_string())?
}
#[tauri::command]
fn get_logs(state: State<'_, AppState>) -> Vec<String> {
    state.service.logs.lock().unwrap().iter().cloned().collect()
}
#[tauri::command]
fn export_logs(app: tauri::AppHandle, state: State<'_, AppState>) -> Result<String, String> {
    let dir = app
        .path()
        .app_local_data_dir()
        .map_err(|e| e.to_string())?
        .join("diagnostics");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let p = dir.join(format!("mklink-{stamp}.log"));
    std::fs::write(
        &p,
        state
            .service
            .logs
            .lock()
            .unwrap()
            .iter()
            .cloned()
            .collect::<Vec<_>>()
            .join("\n"),
    )
    .map_err(|e| e.to_string())?;
    Ok(p.display().to_string())
}
#[tauri::command]
fn install_job(state: State<'_, AppState>) -> Job {
    state.service.job.lock().unwrap().clone()
}
#[tauri::command]
fn target_job(state: State<'_, AppState>) -> target::TargetJob {
    state.service.target.lock().unwrap().clone()
}
#[tauri::command]
async fn inspect_node_firmware(path:String)->Result<Value,String>{
    tauri::async_runtime::spawn_blocking(move||node_update::inspect(&path)).await.map_err(|e|e.to_string())?
}
#[tauri::command]
fn start_node_update(state:State<'_,AppState>,path:String,sha:String,node:String,lease:String)->Result<(),String>{
    node_update::start(state.service.clone(),path,sha,node,lease)
}
#[tauri::command]
fn start_target(app: tauri::AppHandle, state: State<'_, AppState>, request: Value) -> Result<(), String> {
    if state.service.shared.lock().unwrap().is_some(){return Err("请使用共享调试工作台；设备由同一后台持有".into());}
    let tool = resource(&app, "resources/device-tool/mklink-target-tool.exe")?;
    target::start(state.service.clone(), tool, request)
}
#[tauri::command]
fn stop_target(state: State<'_, AppState>) -> Result<(), String> {
    target::request_stop(&state.service)
}
#[tauri::command]
async fn shared_control(app:tauri::AppHandle,state:State<'_,AppState>,method:String,params:Value)->Result<Value,String>{
    let service=state.service.clone();
    let root=resource(&app,"resources")?;
    tauri::async_runtime::spawn_blocking(move || {
        let _gate=service.operation_gate.lock().unwrap();
        if service.target.lock().unwrap().running || service.job.lock().unwrap().running { return Err("请等待当前设备任务完成".into()); }
        let mut shared=service.shared.lock().unwrap();
        if method=="attach" {
            if shared.is_some(){return Err("已经连接共享后台".into());}
            *service.link.lock().unwrap()=None;
            let mut client=shared::Client::open(&root,params)?;
            let status=client.call("status",json!({}))?;
            let status=shared::attach_payload(status,&client);
            *shared=Some(client);
            return Ok(status);
        }
        if method=="detach" {
            if let Some(client)=shared.as_mut(){client.call("detach",json!({}))?;}
            *shared=None;return Ok(json!({"detached":true}));
        }
        if !["status","call","job.start","job.status"].contains(&method.as_str()){return Err("不支持的共享操作".into());}
        let client=shared.as_mut().ok_or("尚未接入共享后台")?;
        client.call(&method,params)
    }).await.map_err(|e|e.to_string())?
}
#[tauri::command]
async fn shared_browser(app:tauri::AppHandle,state:State<'_,AppState>)->Result<(),String>{
    // WebView2 creation must run outside a synchronous Tauri command.
    let url:tauri::Url={
        let shared=state.service.shared.lock().unwrap();
        let client=shared.as_ref().ok_or("尚未接入共享后台")?;
        client.browser_url.parse().map_err(|_|"共享界面地址无效")?
    };
    if url.scheme()!="http" || url.host_str()!=Some("127.0.0.1") || url.path()!="/_runtime/open" {return Err("仅允许已验证的本机共享界面".into());}
    // The existing MKLink UI must run as a browser client: another Tauri
    // host exposes a different IPC API and is not its native application.
    app.opener().open_url(url.as_str(), None::<&str>).map_err(|e|e.to_string())

}
#[tauri::command]
async fn choose_target_path(app: tauri::AppHandle, kind: String) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let dialog = app.dialog().file();
        let chosen = match kind.as_str() {
            "project" => dialog.set_title("选择目标工程目录").blocking_pick_folder(),
            "firmware" => dialog.set_title("选择内部 APP 固件").add_filter("APP 固件", &["axf","elf","bin"]).blocking_pick_file(),
            "symbols" => dialog.set_title("选择 AXF / ELF 符号文件").add_filter("符号文件", &["axf","elf"]).blocking_pick_file(),
            "node_firmware" => dialog.set_title("选择 ESP32-S3 无线节点 APP").add_filter("节点 APP", &["bin"]).blocking_pick_file(),
            _ => return Err("不支持的文件选择类型".into()),
        };
        chosen.map(|path|path.into_path().map(|p|p.to_string_lossy().into_owned()).map_err(|e|e.to_string())).transpose()
    }).await.map_err(|e|e.to_string())?
}
fn resource(app: &tauri::AppHandle, path: &str) -> Result<PathBuf, String> {
    let bundled = app
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join(path);
    if bundled.exists() {
        return Ok(bundled);
    }
    let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path);
    if dev.exists() {
        Ok(dev)
    } else {
        Err("内置工具或默认固件缺失，请使用完整安装包".into())
    }
}
fn copy_firmware_bundle(source:&std::path::Path,dest:&std::path::Path)->Result<(),String>{
    let manifest:Value=serde_json::from_slice(&std::fs::read(source.join("manifest.json")).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
    let images=manifest["images"].as_array().ok_or("Invalid firmware manifest")?;
    let mut names=vec!["manifest.json","README.txt","flash_args"];
    for image in images {let name=image["file"].as_str().ok_or("Invalid firmware image")?;
        if !matches!(std::path::Path::new(name).components().collect::<Vec<_>>().as_slice(),[std::path::Component::Normal(_)]) {return Err("Invalid bundled image path".into());}
        names.push(name);
    }
    for name in names {std::fs::copy(source.join(name),dest.join(name)).map_err(|e|e.to_string())?;}
    Ok(())
}
#[tauri::command]
fn export_firmware(app: tauri::AppHandle) -> Result<String, String> {
    let source = resource(&app, "resources/firmware")?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let dir = app
        .path()
        .download_dir()
        .map_err(|e| e.to_string())?
        .join(format!(
            "mklink-n16r8-default-{stamp}-{}",
            &uuid::Uuid::new_v4().to_string()[..8]
        ));
    std::fs::create_dir(&dir).map_err(|e| e.to_string())?;
    copy_firmware_bundle(&source,&dir)?;
    Ok(dir.display().to_string())
}
#[tauri::command]
fn start_install(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    port: String,
) -> Result<(), String> {
    let _gate = state.service.operation_gate.lock().unwrap();
    if state.service.shared.lock().unwrap().is_some(){return Err("请先退出共享调试，再安装节点固件".into());}
    if state.service.target.lock().unwrap().running { return Err("目标操作正在运行，不能安装节点固件".into()); }
    let tool = resource(&app, "resources/device-tool/mklink-device-tool.exe")?;
    let firmware = resource(&app, "resources/firmware/manifest.json")?;
    if !serialport::available_ports()
        .map_err(|e| e.to_string())?
        .iter()
        .any(|p| p.port_name == port)
    {
        return Err("所选串口不存在".into());
    }
    let dir = app
        .path()
        .app_local_data_dir()
        .map_err(|e| e.to_string())?
        .join("backups");
    let s = state.service.clone();
    {
        let mut job = s.job.lock().unwrap();
        if job.running {
            return Err("安装任务正在运行".into());
        }
        *job = Job {
            running: true,
            stage: "connecting".into(),
            detail: "检查芯片身份与 Flash".into(),
            ..Default::default()
        };
    }
    std::thread::spawn(move || {
        *s.link.lock().unwrap() = None;
        let result = (|| -> Result<(), String> {
            let mut command = Command::new(tool);
            command
                .args([
                    "--port",
                    &port,
                    "--manifest",
                    &firmware.to_string_lossy(),
                    "--backup-dir",
                    &dir.to_string_lossy(),
                ])
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                command.creation_flags(0x08000000);
            }
            let mut child = command.spawn().map_err(|e| e.to_string())?;
            let stderr = child.stderr.take().unwrap();
            let error_reader = std::thread::spawn(move || {
                let mut text = String::new();
                let _ = BufReader::new(stderr).read_to_string(&mut text);
                text
            });
            for line in BufReader::new(child.stdout.take().unwrap()).lines() {
                let line = line.map_err(|e| e.to_string())?;
                if let Some(payload) = line.strip_prefix("@TOOL ") {
                    if let Ok(v) = serde_json::from_str::<Value>(payload) {
                        let mut j = s.job.lock().unwrap();
                        if let Some(v) = v["stage"].as_str() {
                            j.stage = v.into();
                        }
                        if let Some(v) = v["done"].as_u64() {
                            j.done = v;
                        }
                        if let Some(v) = v["total"].as_u64() {
                            j.total = v;
                        }
                        if let Some(v) = v["detail"].as_str() {
                            j.detail = v.into();
                        }
                        if let Some(v) = v["backup_path"].as_str() {
                            j.backup_path = v.into();
                        }
                    }
                } else {
                    s.log(&line);
                }
            }
            let status = child.wait().map_err(|e| e.to_string())?;
            let errors = error_reader.join().unwrap_or_default();
            if !status.success() {
                return Err(if errors.is_empty() {
                    "安装失败；已停止，请查看诊断日志和备份".into()
                } else {
                    errors.chars().take(1500).collect()
                });
            }
            Ok(())
        })();
        let mut j = s.job.lock().unwrap();
        j.running = false;
        match result {
            Ok(()) => {
                j.stage = "complete".into();
                j.done = 100;
                j.total = 100;
                j.detail = "默认固件已安装并校验，可连接配置接口".into();
            }
            Err(e) => {
                j.stage = "failed".into();
                j.error = e;
            }
        }
    });
    Ok(())
}
#[tauri::command]
async fn agent_call(method:String,params:Value)->Result<Value,String>{
    tauri::async_runtime::spawn_blocking(move||agent::request(&method,params)).await.map_err(|e|e.to_string())?
}

#[tauri::command]
async fn agent_open_browser(app:tauri::AppHandle)->Result<(),String>{
    let data=tauri::async_runtime::spawn_blocking(||agent::request("shared_browser",json!({}))).await.map_err(|e|e.to_string())??;
    let url:tauri::Url=data["url"].as_str().ok_or("Missing browser URL")?.parse().map_err(|_|"Invalid URL")?;
    if url.scheme()!="http"||url.host_str()!=Some("127.0.0.1")||url.path()!="/_runtime/open"{return Err("Invalid local shared browser URL".into());}
    app.opener().open_url(url.as_str(),None::<&str>).map_err(|e|e.to_string())
}

pub fn run() {run_mode(false);}
pub fn run_mode(headless:bool) {
    let mut context=tauri::generate_context!();
    if headless{context.config_mut().app.windows.clear();}
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(AppState {
            service: Arc::new(Service::default()),
        })
        .setup(|app|{agent::start(app.handle().clone()).map_err(std::io::Error::other)?;Ok(())})
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let state=window.state::<AppState>();
                if state.service.job.lock().unwrap().running || state.service.target.lock().unwrap().running {
                    api.prevent_close();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            agent_call,
            agent_open_browser,
            list_ports,
            connect_serial,
            connect_lan,
            list_ble,
            connect_ble,
            disconnect,
            rpc,
            get_logs,
            export_logs,
            export_firmware,
            start_install,
            install_job,
            target_job,
            start_target,
            stop_target,
            inspect_node_firmware,
            start_node_update,
            choose_target_path,
            shared_control,
            shared_browser
        ])
        .run(context)
        .expect("Tauri runtime error");
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn serial_fragmentation_and_coalesced_tail() {
        let mut pending=b"partial log@MKC".to_vec();
        assert!(drain_serial_reply(&mut pending,"a",|_|{}).is_none());
        pending.extend_from_slice(b"FG {\"id\":\"a\",\"v\":1,\"ok\":true,\"data\":{}}\nnext");
        assert_eq!(drain_serial_reply(&mut pending,"a",|_|{}).unwrap()["id"],"a");
        assert_eq!(&pending,b"next");
    }
    #[test]
    fn stale_serial_reply_is_never_logged_or_used() {
        let mut pending=b"@MKCFG {\"id\":\"old\",\"secret\":\"private\"}\nlog line\n".to_vec();
        let mut logs=Vec::new();
        assert!(drain_serial_reply(&mut pending,"current",|s|logs.push(s.to_string())).is_none());
        assert_eq!(logs,vec!["log line"]);
    }
    #[test]
    fn lan_origin_scope() {
        assert!(validate_lan("http://192.168.1.42:8080").is_ok());
        assert!(validate_lan("http://127.0.0.1:8080").is_ok());
        for u in [
            "https://192.168.1.1",
            "http://8.8.8.8",
            "file:///tmp/a",
            "http://a:b@192.168.1.1",
            "http://192.168.1.1/a",
            "http://192.168.1.1/?q=x",
        ] {
            assert!(validate_lan(u).is_err(), "{u}");
        }
    }
}

#[cfg(test)]
mod transport_tests {
    use super::*;
    fn exercise(mode: &str) -> Result<Value, String> {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let mode = mode.to_owned();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut bytes = Vec::new();
            let mut byte = [0];
            while !bytes.ends_with(b"\r\n\r\n") {
                stream.read_exact(&mut byte).unwrap();
                bytes.push(byte[0]);
            }
            let header = String::from_utf8(bytes).unwrap();
            assert!(header.starts_with("POST /api/v1/rpc HTTP/1.1"));
            assert!(header
                .to_ascii_lowercase()
                .contains("authorization: bearer 00000000000000000000000000000000"));
            let length = header
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length: ")
                        .map(|s| s.parse::<usize>().unwrap())
                })
                .unwrap();
            let mut body = vec![0; length];
            stream.read_exact(&mut body).unwrap();
            let request: Value = serde_json::from_slice(&body).unwrap();
            assert_eq!(request["method"], "get_config");
            let id = if mode == "wrong-id" {
                json!("stale-response")
            } else {
                request["id"].clone()
            };
            let response = if mode == "oversize" {
                "x".repeat(65537)
            } else {
                json!({"v":1,"id":id,"ok":true,"data":{"revision":7}}).to_string()
            };
            write!(stream,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",response.len(),response).unwrap();
        });
        let service = Service::default();
        *service.link.lock().unwrap() = Some(Link::Lan {
            url: format!("http://{address}"),
            token: "00000000000000000000000000000000".into(),
        });
        let result = service.rpc("get_config", json!({}));
        server.join().unwrap();
        result
    }
    #[test]
    fn lan_request_and_reply_contract() {
        assert_eq!(exercise("valid").unwrap()["revision"], 7);
    }
    #[test]
    fn stale_reply_rejected() {
        assert!(exercise("wrong-id").unwrap_err().contains("标识不匹配"));
    }
    #[test]
    fn oversized_reply_rejected() {
        assert!(exercise("oversize").unwrap_err().contains("超过限制"));
    }
}
