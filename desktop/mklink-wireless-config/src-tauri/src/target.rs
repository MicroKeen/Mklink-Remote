//! Native SDK worker frames use the already-owned desktop connection.
use crate::Service;
use serde::Serialize;
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::{atomic::Ordering, Arc};

#[derive(Clone, Default, Serialize)]
pub struct TargetJob {
    pub id: String,
    pub node_id: String,
    pub running: bool,
    pub action: String,
    pub phase: String,
    pub done: u64,
    pub total: u64,
    pub error: String,
    pub result: Value,
    pub rtt: Vec<Value>,
    pub display_dropped_frames: u64,
}

pub fn run_worker(service: &Arc<Service>, tool: &Path, request: Value) -> Result<Value, String> {
    let mut command = Command::new(tool);
    command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn().map_err(|e| format!("无法启动目标调试组件：{e}"))?;
    let mut input = child.stdin.take().ok_or("目标工具输入管道缺失")?;
    writeln!(input, "{}", request).map_err(|e| e.to_string())?;
    let stderr = child.stderr.take().ok_or("目标工具诊断管道缺失")?;
    let diagnostics = std::thread::spawn(move || {
        let mut source = BufReader::new(stderr);
        let mut kept = Vec::new();
        let mut chunk = [0u8; 4096];
        loop {
            match source.read(&mut chunk) {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    let remaining = 65536usize.saturating_sub(kept.len());
                    kept.extend_from_slice(&chunk[..n.min(remaining)]);
                }
            }
        }
        String::from_utf8_lossy(&kept).into_owned()
    });
    let mut output = BufReader::new(child.stdout.take().ok_or("目标工具输出管道缺失")?);
    let mut completed: Option<Result<Value, String>> = None;
    let result = (|| -> Result<(), String> {
        loop {
            let mut line = Vec::new();
            // Bound all worker frames, including final RTT captures. Never
            // log credential-bearing broker requests or response bodies.
            let n = output.by_ref().take(262145).read_until(b'\n', &mut line).map_err(|e| e.to_string())?;
            if n == 0 { break; }
            if n > 262144 || !line.ends_with(b"\n") { return Err("目标工具帧超过限制或连接中断；不会重放".into()); }
            let frame: Value = serde_json::from_slice(&line).map_err(|_| "目标工具返回无效协议".to_string())?;
            match frame["kind"].as_str().unwrap_or("") {
                "rpc" => {
                    let method = frame["method"].as_str().ok_or("目标工具缺少 RPC 方法")?;
                    let response = match service.rpc(method, frame["params"].clone()) {
                        Ok(data) => json!({"id":frame["id"],"ok":true,"data":data}),
                        Err(error) => json!({"id":frame["id"],"ok":false,"error":error}),
                    };
                    let mut response = response;
                    response["stop_requested"] = json!(service.target_stop.load(Ordering::SeqCst));
                    writeln!(input, "{response}").map_err(|e| e.to_string())?;
                    input.flush().map_err(|e| e.to_string())?;
                }
                "progress" => {
                    let mut job = service.target.lock().unwrap();
                    job.phase = frame["phase"].as_str().unwrap_or("working").into();
                    job.done = frame["done"].as_u64().unwrap_or(0);
                    job.total = frame["total"].as_u64().unwrap_or(0);
                }
                "rtt" => {
                    let mut job = service.target.lock().unwrap();
                    if job.rtt.len() == 256 { job.rtt.remove(0); job.display_dropped_frames += 1; }
                    job.rtt.push(frame);
                }
                "result" => {
                    if completed.is_some() { return Err("目标工具返回重复终态".into()); }
                    completed = Some(if frame["ok"] == true { Ok(frame["data"].clone()) }
                        else { Err(frame["error"].as_str().unwrap_or("目标操作失败").to_string()) });
                }
                _ => return Err("未知目标工具帧".into()),
            }
        }
        Ok(())
    })();
    drop(input);
    if result.is_err() {
        // Closing stdin makes further broker requests fail. Drain output so a
        // worker reporting cleanup cannot block on a full pipe while we wait.
        let _ = std::io::copy(&mut output, &mut std::io::sink());
    }
    let exit = child.wait().map_err(|e| e.to_string())?;
    let diagnostic = diagnostics.join().unwrap_or_default();
    result?;
    match completed {
        Some(Ok(data)) if exit.success() => Ok(data),
        Some(Err(error)) => Err(error),
        _ => Err(format!("目标工具没有成功终态；不会重试。{}", diagnostic.chars().take(400).collect::<String>())),
    }
}

pub fn request_stop(service: &Service) -> Result<(), String> {
    let job=service.target.lock().unwrap();
    if !job.running || !["prepare_flash","rtt","superwatch","rtos_trace"].contains(&job.action.as_str()) {
        return Err("当前阶段不可停止；烧录开始后需等待校验完成".into());
    }
    service.target_stop.store(true,Ordering::SeqCst);Ok(())
}

pub fn start(service: Arc<Service>, tool: std::path::PathBuf, request: Value) -> Result<(), String> {
    let action = request["action"].as_str().ok_or("缺少目标操作")?.to_string();
    if !["inspect", "identify", "read", "write", "prepare_flash", "flash", "verify_flash", "benchmark", "rtt", "superwatch", "rtos_trace", "binary_read", "performance"].contains(&action.as_str()) {
        return Err("不支持的目标操作".into());
    }
    {
        let _gate = service.operation_gate.lock().unwrap();
        if service.shared.lock().unwrap().is_some(){return Err("请通过共享调试后台操作目标".into());}
        if service.job.lock().unwrap().running { return Err("节点固件安装正在运行".into()); }
        let mut job = service.target.lock().unwrap();
        if job.running { return Err("目标操作正在运行，请等待完成".into()); }
        service.target_stop.store(false, Ordering::SeqCst);
        *job = TargetJob { id:uuid::Uuid::new_v4().to_string(),node_id:request["node_id"].as_str().unwrap_or("").into(),running:true, action:action.clone(), phase:"connecting".into(), ..Default::default() };
    }
    std::thread::spawn(move || {
        let result = run_worker(&service, &tool, request);
        let mut job = service.target.lock().unwrap();
        job.running = false;
        match result {
            Ok(data) => { job.phase = "complete".into(); job.result = data; }
            Err(error) => { job.phase = "failed".into(); job.error = error; }
        }
    });
    Ok(())
}
