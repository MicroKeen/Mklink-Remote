//! A client of the existing MKLink runtime; this process never owns V4 IO.
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver, Sender};
use std::time::Duration;

pub struct Client {
    child: Child,
    input: Option<Sender<Value>>,
    output: Receiver<Result<Value, String>>,
    sequence: u64,
    pub browser_url: String,
}
impl Client {
    pub fn open(resource: &Path, request: Value) -> Result<Self, String> {
        let mut client = Self::start(resource)?;
        let result = client.call("attach", request)?;
        client.browser_url = result["browser_url"].as_str().ok_or("共享界面地址缺失")?.into();
        Ok(client)
    }
    pub fn saved_nodes(resource: &Path) -> Result<Value, String> {
        Self::start(resource)?.call("saved_nodes", json!({}))
    }
    fn start(resource: &Path) -> Result<Self, String> {
        let executable = resource.join("device-tool/remote-server/mklink-remote-server.exe");
        let mut command = if executable.is_file() {
            let mut command = Command::new(executable);
            command.arg("s3-workbench");
            command
        } else {
            // Development-only local configuration. Never shipped with local paths.
            let file = resource.join("device-tool/remote-runtime.local.json");
            let cfg: Value = serde_json::from_slice(&std::fs::read(file).map_err(|_| "共享后台组件尚未安装")?)
                .map_err(|_| "共享后台配置无效")?;
            let mut command = Command::new(cfg["python"].as_str().ok_or("共享 Python 路径缺失")?);
            command.args(["-m", "mklink_remote", "s3-workbench"]);
            if let Some(source)=cfg["source"].as_str(){command.env("PYTHONPATH",source).current_dir(source);}
            if let Some(root) = cfg["runtime_dir"].as_str() { command.env("MKLINK_RUNTIME_DIR", root); }
            if let Some(root) = cfg["flm_root"].as_str() { command.env("MKLINK_BUILTIN_FLM_ROOT", root); }
            command
        };
        Self::spawn(&mut command)
    }
    fn spawn(command: &mut Command) -> Result<Self, String> {
        command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
        #[cfg(windows)] {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let mut child = command.spawn().map_err(|e| format!("无法启动共享后台客户端：{e}"))?;
        let mut input = child.stdin.take().ok_or("共享客户端输入缺失")?;
        let mut output = BufReader::new(child.stdout.take().ok_or("共享客户端输出缺失")?);
        let (send, requests) = mpsc::channel();
        let (replies, receive) = mpsc::channel();
        std::thread::spawn(move || {
            for request in requests {
                let result = exchange(&mut input, &mut output, &request);
                let failed = result.is_err();
                if replies.send(result).is_err() || failed { break; }
            }
        });
        Ok(Self { child, input:Some(send), output:receive, sequence:0, browser_url:String::new() })
    }
    pub fn call(&mut self, method: &str, params: Value) -> Result<Value, String> {
        // Keep long captures within their existing backend budget; status/exit stay bounded.
        let seconds = match method {
            "attach" => 120,
            "call" => match params["capability"].as_str() {
                Some("dump_memory") => 4200, // 64 samples × (60 s read + 5 s cleanup), plus framing.
                Some("capture_dump") => 360,
                Some("offline_deploy") => 700,
                _ => 120,
            },
            _ => 45,
        };
        self.call_with_timeout(method, params, Duration::from_secs(seconds))
    }
    fn call_with_timeout(&mut self, method: &str, params: Value, timeout: Duration) -> Result<Value, String> {
        self.sequence += 1;
        let result = (|| {
            self.input.as_ref().ok_or("共享客户端已退出")?
                .send(json!({"id":self.sequence,"method":method,"params":params}))
                .map_err(|_| "共享客户端已退出；不重试".to_string())?;
            self.output.recv_timeout(timeout)
                .map_err(|_| "共享客户端未响应；操作结果未知，不重试，请查询后台任务状态".to_string())?
        })();
        let reply = match result {
            Ok(reply) => reply,
            Err(error) => {
                self.input.take();
                // Only retire our IPC sidecar, never the independent runtime or its jobs.
                let _ = self.child.kill();
                let _ = self.child.wait();
                return Err(error);
            }
        };
        if reply["ok"] != true { return Err(reply["error"].as_str().unwrap_or("共享操作失败").into()); }
        Ok(reply["data"].clone())
    }
}

fn exchange(input: &mut impl Write, output: &mut impl BufRead, request: &Value) -> Result<Value, String> {
    writeln!(input, "{request}").map_err(|_| "共享客户端写入失败；不重试")?;
    input.flush().map_err(|_| "共享客户端写入结果未知；不重试")?;
    let mut line = Vec::new();
    use std::io::Read;
    let size = output.take(1048577).read_until(b'\n', &mut line).map_err(|_| "共享客户端读取失败；不重试")?;
    if size > 1048576 || !line.ends_with(b"\n") { return Err("共享客户端响应中断；不重试".into()); }
    let reply: Value = serde_json::from_slice(&line).map_err(|_| "共享客户端响应格式无效")?;
    if reply["id"] != request["id"] { return Err("共享客户端响应不匹配".into()); }
    Ok(reply)
}

pub fn detach(shared: &mut Option<Client>) -> Value {
    let error = shared.take().and_then(|mut client| client.call("detach", json!({})).err());
    match error {
        Some(error) => json!({"detached":true,"backend_detach_confirmed":false,
            "warning":format!("已退出本窗口；后台释放未确认，任务可能仍在运行。重新接入后先查询任务状态，不要重复下载。{error}")}),
        None => json!({"detached":true,"backend_detach_confirmed":true}),
    }
}
impl Drop for Client {
    fn drop(&mut self) {
        // EOF detaches just this client. Never kill the shared runtime/AI jobs.
        self.input.take();
        let _ = self.child.try_wait();
    }
}

pub fn attach_payload(mut status: Value, client: &Client) -> Value {
    status["browser_available"] = json!(!client.browser_url.is_empty());
    status
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn framing_rejects_truncation_wrong_ids_and_oversized_replies() {
        let request = json!({"id":1});
        for bytes in [b"{\"id\":1}".to_vec(), b"{\"id\":2}\n".to_vec(), vec![b'x';1048577]] {
            assert!(exchange(&mut Vec::new(), &mut Cursor::new(bytes), &request).is_err());
        }
        let reply=exchange(&mut Vec::new(), &mut Cursor::new(b"{\"id\":1,\"ok\":false,\"error\":\"rejected\"}\n"), &request).unwrap();
        assert_eq!(reply["ok"], false);
    }

    #[cfg(windows)]
    fn sidecar(script: &str) -> Client {
        Client::spawn(Command::new("powershell.exe").args(["-NoLogo","-NoProfile","-NonInteractive","-Command",script])).unwrap()
    }

    #[cfg(windows)]
    #[test]
    fn dead_sidecar_detaches_locally_without_claiming_backend_release() {
        let mut client=sidecar("Start-Sleep -Seconds 60");
        client.child.kill().unwrap();client.child.wait().unwrap();
        let mut slot=Some(client);
        let result=detach(&mut slot);
        assert!(slot.is_none());
        assert_eq!(result["detached"],true);
        assert_eq!(result["backend_detach_confirmed"],false);
        assert!(result["warning"].as_str().unwrap().contains("任务可能仍在运行"));
    }

    #[cfg(windows)]
    #[test]
    fn stalled_sidecar_is_retired_and_request_is_not_replayed() {
        let mut client=sidecar("$null=[Console]::ReadLine(); [Console]::Out.Write('{\"id\":1'); [Console]::Out.Flush(); Start-Sleep -Seconds 60");
        let started=std::time::Instant::now();
        assert!(client.call_with_timeout("status",json!({}),Duration::from_millis(500)).is_err());
        assert!(started.elapsed()<Duration::from_secs(5));
        assert!(client.child.try_wait().unwrap().is_some());
        assert!(client.input.is_none());
        assert!(client.call("status",json!({})).is_err());
    }

    #[cfg(windows)]
    #[test]
    fn application_error_preserves_channel_for_confirmed_detach() {
        let mut client=sidecar("$null=[Console]::ReadLine(); [Console]::WriteLine('{\"id\":1,\"ok\":false,\"error\":\"rejected\"}'); $null=[Console]::ReadLine(); [Console]::WriteLine('{\"id\":2,\"ok\":true,\"data\":{}}')");
        assert_eq!(client.call("call",json!({})).unwrap_err(),"rejected");
        let mut slot=Some(client);
        assert_eq!(detach(&mut slot)["backend_detach_confirmed"],true);
        assert!(slot.is_none());
    }
}
