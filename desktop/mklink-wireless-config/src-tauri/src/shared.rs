//! A client of the existing MKLink runtime; this process never owns V4 IO.
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};

pub struct Client {
    child: Child,
    input: Option<ChildStdin>,
    output: BufReader<ChildStdout>,
    sequence: u64,
    pub browser_url: String,
}
impl Client {
    pub fn open(resource: &Path, request: Value) -> Result<Self, String> {
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
        command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
        #[cfg(windows)] {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let mut child = command.spawn().map_err(|e| format!("无法启动共享后台客户端：{e}"))?;
        let input = child.stdin.take().ok_or("共享客户端输入缺失")?;
        let output = BufReader::new(child.stdout.take().ok_or("共享客户端输出缺失")?);
        let mut client = Self { child, input:Some(input), output, sequence:0, browser_url:String::new() };
        let result = client.call("attach", request)?;
        client.browser_url = result["browser_url"].as_str().ok_or("共享界面地址缺失")?.into();
        Ok(client)
    }
    pub fn call(&mut self, method: &str, params: Value) -> Result<Value, String> {
        self.sequence += 1;
        let input = self.input.as_mut().ok_or("共享客户端已退出")?;
        writeln!(input, "{}", json!({"id":self.sequence,"method":method,"params":params})).map_err(|_| "共享客户端写入失败；不重试")?;
        input.flush().map_err(|_| "共享客户端写入结果未知；不重试")?;
        let mut line = Vec::new();
        use std::io::Read;
        let size = self.output.by_ref().take(1048577).read_until(b'\n', &mut line).map_err(|_| "共享客户端读取失败；不重试")?;
        if size > 1048576 || !line.ends_with(b"\n") { return Err("共享客户端响应中断；不重试".into()); }
        let reply: Value = serde_json::from_slice(&line).map_err(|_| "共享客户端响应格式无效")?;
        if reply["id"].as_u64() != Some(self.sequence) { return Err("共享客户端响应不匹配".into()); }
        if reply["ok"] != true { return Err(reply["error"].as_str().unwrap_or("共享操作失败").into()); }
        Ok(reply["data"].clone())
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
