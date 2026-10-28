//! Local authenticated automation surface. Every operation delegates to the same
//! native command used by the GUI. It never creates a second device connection.
use super::*;
use std::net::{TcpListener,TcpStream};
use std::path::Path;

const MAX:usize=1024*1024;
const RESPONSE_MAX:usize=16*1024*1024;
const METHODS:&[(&str,&str)]=&[
    ("preferences_get","{}"),("preferences_set",r#"{"theme":"dark|light","skin":"technical|aurora|sand","page":"overview|shared|network|gateway|logs|update|install|help"}"#),
    ("service_stop","{}"),("service_status","{}"),
    ("list_ports","{}"),("list_ble","{}"),
    ("connect_serial",r#"{"port":"COM…"}"#),
    ("connect_lan",r#"{"url":"http://device","token":"USB pairing secret"}"#),
    ("connect_ble",r#"{"address":"02:00:00:12:34:56","token":"USB pairing secret"}"#),
    ("disconnect","{}"),
    ("rpc",r#"{"method":"get_status","params":{}}"#),
    ("get_logs","{}"),("export_logs",r#"{"directory":"optional output directory"}"#),
    ("diagnostics_query",r#"{"level":"all|info|warning|error","search":"optional text"}"#),
    ("diagnostics_export",r#"{"level":"all|info|warning|error","search":"optional text","format":"txt|json","directory":"optional output directory"}"#),
    ("export_firmware",r#"{"directory":"optional new output directory"}"#),
    ("start_install",r#"{"port":"COM…"}"#),("install_job","{}"),
    ("inspect_node_firmware",r#"{"path":"absolute node APP path"}"#),
    ("start_node_update",r#"{"path":"node APP","sha":"sha256","node":"node ID","lease":"lease token"}"#),
    ("start_target",r#"{"request":{"action":"identify","node_id":"12 hex digits","project_root":"absolute directory","axf":"optional matching ELF","params":{}}}"#),
    ("stop_target","{}"),("target_job","{}"),
    ("shared_control",r#"{"method":"attach|status|call|job.start|job.status|detach","params":{}}"#),
    ("shared_browser","{}"),
    ("choose_target_path",r#"{"path":"explicit existing file or directory"}"#),
];

pub fn capabilities()->Value {
    json!({"protocol":1,"product":"Mklink Remote","version":env!("CARGO_PKG_VERSION"),
      "commands":METHODS.iter().map(|(name,args)|json!({"name":name,"arguments":args})).collect::<Vec<_>>(),
      "node_rpc_methods":NODE_RPC_METHODS,
      "target_actions":["inspect","identify","read","write","prepare_flash","flash","verify_flash","benchmark","rtt","superwatch","rtos_trace","binary_read","performance"],
      "workflow":["discover ports/radios","connect","rpc pair/get_status/get_config","acquire control for configuration","shared_control attach","original MKLink MCP joins registered site","poll jobs; do not replay unknown writes"],
      "notes":["stdin/params file for secrets; never command-line tokens","GUI and CLI control the same local service","shared_browser returns a private local URL","file dialogs use explicit paths from CLI","original MKLink skill and MCP are unchanged"]})
}

fn field(p:&Value,key:&str)->Result<String,String>{p[key].as_str().map(str::to_owned).ok_or_else(||format!("Missing string: {key}"))}
pub fn dispatch(app:&tauri::AppHandle,method:&str,p:Value)->Result<Value,String>{
    let state=app.state::<AppState>();
    let unit=|r:Result<(),String>|r.map(|_|json!({"accepted":true}));
    let block=tauri::async_runtime::block_on;
    match method {
        "capabilities"=>Ok(capabilities()),
        "ping"=>Ok(json!({"protocol":1,"version":env!("CARGO_PKG_VERSION"),"pid":std::process::id()})),
        "service_status"=>{
            let management=state.service.link.try_lock().ok().map(|link|json!({"connected":link.is_some(),"transport":match link.as_ref(){Some(Link::Serial{..})=>"usb",Some(Link::Lan{..})=>"lan",Some(Link::Ble(_))=>"ble",None=>"none"},"revision":state.service.link_revision.load(std::sync::atomic::Ordering::Relaxed)}));
            let shared=state.service.shared.try_lock().ok().map(|client|client.is_some());
            Ok(json!({"management":management,"shared":shared}))
        },
        "preferences_get"=>Ok(state.service.preferences.lock().unwrap().clone()),
        "preferences_set"=>{
            let fields=p.as_object().ok_or("Preferences must be an object")?;
            for (key,value) in fields{
                let allowed:&[&str]=match key.as_str(){"theme"=>&["dark","light"],"skin"=>&["technical","aurora","sand"],"page"=>&["overview","shared","network","gateway","logs","update","install","help","target"],_=>return Err("Unknown preference".into())};
                if !allowed.contains(&value.as_str().ok_or("Preference must be a string")?){return Err("Unsupported preference value".into());}
            }
            let mut prefs=state.service.preferences.lock().unwrap();let mut next=prefs.clone();
            for (key,value) in fields{next[key]=value.clone();}
            next["revision"]=json!(prefs["revision"].as_u64().unwrap_or(0)+1);
            let path=endpoint_path().with_file_name("preferences.json");
            let temp=path.with_extension("tmp");std::fs::write(&temp,serde_json::to_vec(&next).unwrap()).map_err(|e|e.to_string())?;
            std::fs::rename(temp,path).map_err(|e|e.to_string())?;*prefs=next;Ok(prefs.clone())
        },
        "service_stop"=>{
            let _gate=state.service.operation_gate.lock().unwrap();
            if state.service.job.lock().unwrap().running||state.service.target.lock().unwrap().running||state.service.shared.lock().unwrap().is_some(){return Err("Finish jobs and detach this service's shared client before stopping".into());}
            *state.service.link.lock().unwrap()=None;
            let app=app.clone();std::thread::spawn(move||{std::thread::sleep(Duration::from_millis(200));app.exit(0);});
            Ok(json!({"stopping":true}))
        },
        "list_ports"=>list_ports(),
        "list_ble"=>serde_json::to_value(ble::list()?).map_err(|e|e.to_string()),
        "connect_serial"=>unit(state.service.connect_serial(&field(&p,"port")?)),
        "connect_lan"=>unit(state.service.connect_lan(field(&p,"url")?,field(&p,"token")?)),
        "connect_ble"=>unit(state.service.connect_ble(field(&p,"address")?,field(&p,"token")?)),
        "disconnect"=>unit(state.service.disconnect()),
        "rpc"=>state.service.rpc(&field(&p,"method")?,p.get("params").cloned().unwrap_or(json!({}))),
        "get_logs"=>Ok(json!(get_logs(state))),
        "diagnostics_query"=>{state.service.collect_backend_logs();state.service.diagnostics.lock().unwrap().query(&p)},
        "diagnostics_export"=>{
            state.service.collect_backend_logs();
            let data=state.service.diagnostics.lock().unwrap().query(&p)?;
            let format=p["format"].as_str().unwrap_or("txt");
            if !["txt","json"].contains(&format){return Err("format must be txt/json".into());}
            let dir=if let Some(dir)=p["directory"].as_str(){PathBuf::from(dir)}else{app.path().download_dir().map_err(|e|e.to_string())?};
            std::fs::create_dir_all(&dir).map_err(|e|e.to_string())?;
            let dest=dir.join(format!("MklinkRemote-diagnostics-{}.{}",uuid::Uuid::new_v4(),format));
            let content=if format=="txt"{diagnostics::text(&data)}else{serde_json::to_string_pretty(&data).unwrap()};
            std::fs::write(&dest,content).map_err(|e|e.to_string())?;
            Ok(json!({"path":dest,"entries":data["matched"],"format":format}))
        },
        "export_logs"=>{
            if let Some(dir)=p["directory"].as_str(){
                let dir=Path::new(dir);std::fs::create_dir_all(dir).map_err(|e|e.to_string())?;
                let dest=dir.join(format!("mklink-{}.log",uuid::Uuid::new_v4()));
                std::fs::write(&dest,get_logs(state).join("\n")).map_err(|e|e.to_string())?;
                Ok(json!(dest))
            }else{export_logs(app.clone(),state).map(|s|json!(s))}
        },
        "export_firmware"=>{
            if let Some(dir)=p["directory"].as_str(){
                let dest=Path::new(dir);std::fs::create_dir(dest).map_err(|e|e.to_string())?;
                let source=resource(app,"resources/firmware")?;
                copy_firmware_bundle(&source,dest)?;
                Ok(json!(dest))
            }else{export_firmware(app.clone()).map(|s|json!(s))}
        },
        "start_install"=>unit(start_install(app.clone(),state,field(&p,"port")?)),
        "install_job"=>Ok(json!(install_job(state))),
        "target_job"=>Ok(json!(target_job(state))),
        "inspect_node_firmware"=>node_update::inspect(&field(&p,"path")?),
        "start_node_update"=>unit(start_node_update(state,field(&p,"path")?,field(&p,"sha")?,field(&p,"node")?,field(&p,"lease")?)),
        "start_target"=>unit(start_target(app.clone(),state,p.get("request").cloned().ok_or("Missing request")?)),
        "stop_target"=>unit(stop_target(state)),
        "shared_control"=>block(shared_control(app.clone(),state,field(&p,"method")?,p.get("params").cloned().unwrap_or(json!({})))),
        "shared_browser"=>{
            let locked=state.service.shared.lock().unwrap();
            let client=locked.as_ref().ok_or("尚未接入共享后台")?;
            Ok(json!({"url":client.browser_url}))
        },
        "choose_target_path"=>{
            let path=std::fs::canonicalize(field(&p,"path")?).map_err(|e|e.to_string())?;
            Ok(json!(path))
        },
        _=>Err("Unknown command; run mklink-remote help".into())
    }
}

pub fn endpoint_path()->PathBuf{
    std::env::var_os("MKLINK_REMOTE_AGENT_DIR").map(PathBuf::from)
        .unwrap_or_else(||PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap_or_else(||".".into())).join("MklinkRemote/agent"))
        .join("endpoint.json")
}
pub fn load_preferences()->Value{
    std::fs::read(endpoint_path().with_file_name("preferences.json")).ok()
        .and_then(|v|serde_json::from_slice(&v).ok()).filter(|v:&Value|v.is_object())
        .unwrap_or(json!({"theme":"dark","skin":"technical","page":"overview","revision":0}))
}

pub fn request(method:&str,params:Value)->Result<Value,String>{
    let data=std::fs::read(endpoint_path()).map_err(|_|"请启动 Mklink Remote，或运行 mklink-remote serve")?;
    let endpoint:Value=serde_json::from_slice(&data).map_err(|_|"Invalid local endpoint")?;
    let port=endpoint["port"].as_u64().filter(|n|*n>0&&*n<=65535).ok_or("Invalid local port")?;
    let token=endpoint["token"].as_str().ok_or("Missing local token")?;
    let client=reqwest::blocking::Client::builder().no_proxy().connect_timeout(Duration::from_secs(2)).timeout(Duration::from_secs(if method=="ping"{3}else{180})).build().map_err(|e|e.to_string())?;
    let id=uuid::Uuid::new_v4().to_string();
    let response=client.post(format!("http://127.0.0.1:{port}/command")).bearer_auth(token)
        .json(&json!({"id":id,"method":method,"params":params})).send()
        .map_err(|_|"本地服务未响应；操作结果未知，不自动重发。先查询状态。")?;
    if !response.status().is_success(){return Err(format!("Local service HTTP {}",response.status()));}
    let mut bytes=Vec::new();response.take((RESPONSE_MAX+1)as u64).read_to_end(&mut bytes).map_err(|e|e.to_string())?;
    if bytes.len()>RESPONSE_MAX{return Err("Local response exceeds limit".into());}
    let reply:Value=serde_json::from_slice(&bytes).map_err(|_|"Invalid local response")?;
    if reply["id"]!=id{return Err("Local response identity mismatch; no replay".into());}
    if reply["ok"]!=true{return Err(reply["error"].as_str().unwrap_or("Command failed").into());}
    Ok(reply["data"].clone())
}

fn protect_directory(dir:&Path)->Result<(),String>{
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        let who=Command::new("whoami").args(["/user","/fo","csv","/nh"]).creation_flags(0x08000000).output().map_err(|e|e.to_string())?;
        let text=String::from_utf8_lossy(&who.stdout);
        let sid=text.trim().split(',').last().unwrap_or("").trim_matches('"');
        if !sid.starts_with("S-1-"){return Err("Cannot determine current user SID".into());}
        let status=Command::new("icacls").arg(dir).args(["/inheritance:r","/grant:r",&format!("*{sid}:(OI)(CI)F")])
            .creation_flags(0x08000000).stdout(Stdio::null()).stderr(Stdio::null()).status().map_err(|e|e.to_string())?;
        if !status.success(){return Err("Cannot protect local Agent credentials".into());}
    }
    #[cfg(unix)] {use std::os::unix::fs::PermissionsExt;std::fs::set_permissions(dir,std::fs::Permissions::from_mode(0o700)).map_err(|e|e.to_string())?;}
    Ok(())
}

fn handle(mut socket:TcpStream,app:tauri::AppHandle,token:Arc<String>){
    let _=socket.set_read_timeout(Some(Duration::from_secs(5)));
    let result=(||->Result<Value,String>{
        let mut reader=BufReader::new(&mut socket);let mut first=String::new();
        reader.by_ref().take(1025).read_line(&mut first).map_err(|e|e.to_string())?;
        if first.trim_end()!="POST /command HTTP/1.1" {return Err("POST required".into());}
        let mut length=None;let mut authenticated=false;let mut total=first.len();
        loop{
            let mut line=String::new();reader.by_ref().take(8193).read_line(&mut line).map_err(|e|e.to_string())?;
            total+=line.len();if total>16384||line.is_empty(){return Err("Invalid headers".into());}
            if line=="\r\n"{break;}
            if let Some((key,value))=line.split_once(':'){
                if key.eq_ignore_ascii_case("authorization"){authenticated=value.trim()==format!("Bearer {}",token);}
                if key.eq_ignore_ascii_case("content-length"){if length.is_some(){return Err("Duplicate length".into());}length=value.trim().parse::<usize>().ok();}
                if key.eq_ignore_ascii_case("origin")||key.eq_ignore_ascii_case("transfer-encoding"){return Err("Browser/cross-origin requests not supported".into());}
            }
        }
        if !authenticated{return Err("Authentication required".into());}
        let length=length.filter(|n|*n<=MAX).ok_or("Invalid content length")?;
        let mut body=vec![0u8;length];reader.read_exact(&mut body).map_err(|e|e.to_string())?;
        let frame:Value=serde_json::from_slice(&body).map_err(|_|"Invalid JSON")?;
        let id=frame["id"].as_str().filter(|s|s.len()<=128).ok_or("Invalid request ID")?;
        let method=frame["method"].as_str().ok_or("Missing method")?;
        // A duplicate request is never retried by this API or CLI. Device writes
        // retain their existing generation/job/request-ID validation.
        Ok(match dispatch(&app,method,frame.get("params").cloned().unwrap_or(json!({}))){
            Ok(data)=>{
                if !["ping","capabilities","service_status","preferences_get","get_logs","diagnostics_query","install_job","target_job","rpc","shared_control"].contains(&method){app.state::<AppState>().service.diagnostics.lock().unwrap().push("info","agent",&format!("{method} completed"));}
                json!({"id":id,"ok":true,"data":data})
            },
            Err(error)=>{
                let error=diagnostics::redact(&error);
                app.state::<AppState>().service.diagnostics.lock().unwrap().push("error","agent",&format!("{method}: {error}"));
                json!({"id":id,"ok":false,"error":error})
            }
        })
    })();
    let (code,body)=match result{Ok(v)=>("200 OK",v),Err(_)=>("400 Bad Request",json!({"ok":false,"error":"Invalid or unauthenticated local request"}))};
    let bytes=serde_json::to_vec(&body).unwrap();
    let _=write!(socket,"HTTP/1.1 {code}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",bytes.len());
    let _=socket.write_all(&bytes);
}

pub fn start(app:tauri::AppHandle)->Result<(),String>{
    // Existing service is reused, including when CLI started it before the GUI.
    if request("ping",json!({})).is_ok(){return Ok(());}
    let path=endpoint_path();let dir=path.parent().unwrap();
    std::fs::create_dir_all(dir).map_err(|e|e.to_string())?;protect_directory(dir)?;
    // The OS releases this handle on crash. Never delete another owner's lock.
    let lock=std::fs::OpenOptions::new().read(true).write(true).create(true).truncate(false).open(dir.join("service.lock")).map_err(|e|e.to_string())?;
    if lock.try_lock().is_err(){
        for _ in 0..20{if request("ping",json!({})).is_ok(){return Ok(());}std::thread::sleep(Duration::from_millis(100));}
        return Err("Agent service startup is already owned; inspect the existing process".into());
    }
    let listener=TcpListener::bind("127.0.0.1:0").map_err(|e|e.to_string())?;
    let port=listener.local_addr().map_err(|e|e.to_string())?.port();
    let token=Arc::new(format!("{}{}",uuid::Uuid::new_v4().simple(),uuid::Uuid::new_v4().simple()));
    let temp=dir.join(format!("{}.json",uuid::Uuid::new_v4()));
    std::fs::write(&temp,serde_json::to_vec(&json!({"protocol":1,"pid":std::process::id(),"port":port,"token":*token})).unwrap()).map_err(|e|e.to_string())?;
    std::fs::rename(temp,&path).map_err(|e|e.to_string())?;
    std::thread::spawn(move||{let _owner=lock;for socket in listener.incoming().flatten(){let app=app.clone();let token=token.clone();std::thread::spawn(move||handle(socket,app,token));}});
    Ok(())
}

pub fn cli(){
    let args:Vec<String>=std::env::args().skip(1).collect();
    if args.first().map(String::as_str)==Some("serve"){super::run_mode(true);return;}
    let result=(||->Result<Value,String>{
        if args.is_empty()||["help","--help","capabilities"].contains(&args[0].as_str()){return Ok(capabilities());}
        let method=if args[0]=="call"{args.get(1).ok_or("Missing method")?.as_str()}else{args[0].as_str()};
        let params=if let Some(i)=args.iter().position(|a|a=="--params-file"){
            let file=args.get(i+1).ok_or("Missing parameter file")?;
            let mut data=Vec::new();
            if file=="-"{std::io::stdin().take((MAX+1)as u64).read_to_end(&mut data).map_err(|e|e.to_string())?;}
            else{std::fs::File::open(file).map_err(|e|e.to_string())?.take((MAX+1)as u64).read_to_end(&mut data).map_err(|e|e.to_string())?;}
            if data.len()>MAX{return Err("Parameters exceed limit".into());}
            serde_json::from_slice(&data).map_err(|_|"Invalid parameter JSON")?
        }else{json!({})};
        request(method,params)
    })();
    match result{Ok(data)=>println!("{}",json!({"ok":true,"data":data})),Err(error)=>{println!("{}",json!({"ok":false,"error":error}));std::process::exit(1);}}
}
