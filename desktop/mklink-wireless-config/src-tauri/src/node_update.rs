//! Stage node APP into the inactive OTA slot using the existing USB/LAN/BLE RPC.
//! Never boot an image implicitly and never replay an uncertain write.
use crate::{Job,Service};
use base64::{engine::general_purpose::STANDARD,Engine};
use serde_json::{json,Value};
use sha2::{Digest,Sha256};
use std::{path::Path,sync::Arc,time::{Duration,Instant}};
const LIMIT:usize=4*1024*1024;
fn field(bytes:&[u8])->Result<&str,String>{
    let end=bytes.iter().position(|v|*v==0).ok_or("固件描述缺少结束符")?;
    std::str::from_utf8(&bytes[..end]).map_err(|_|"固件描述编码无效".into())
}
pub fn inspect_bytes(data:&[u8])->Result<Value,String>{
    if data.len()<1024||data.len()>LIMIT{return Err("请选择不超过4MiB的 ESP32-S3 节点 APP 文件".into());}
    if data[0]!=0xe9||data[12..14]!=[9,0]||data[32..36]!=[0x32,0x54,0xcd,0xab]||
       field(&data[80..112])?!="n16r8_wireless_gateway"||
       !data.windows(b"MKLINK_NODE_OTA_V1\0".len()).any(|w|w==b"MKLINK_NODE_OTA_V1\0"){
        return Err("镜像不是支持 OTA 的本款 S3 节点 APP；请勿选择合并固件、V4 或目标 MCU 固件".into());
    }
    Ok(json!({"bytes":data.len(),"sha256":format!("{:x}",Sha256::digest(data)),"version":field(&data[48..80])?,"project":"n16r8_wireless_gateway"}))
}
pub fn inspect(path:&str)->Result<Value,String>{
    if !Path::new(path).is_file(){return Err("请选择节点 APP 文件".into());}
    let size=std::fs::metadata(path).map_err(|e|e.to_string())?.len();
    if size>LIMIT as u64{return Err("节点 APP 超过4MiB".into());}
    let data=std::fs::read(path).map_err(|e|e.to_string())?;
    let mut info=inspect_bytes(&data)?;info["path"]=json!(path);Ok(info)
}
pub fn stage(service:&Service,data:&[u8],sha:&str,node:&str,lease:&str)->Result<Value,String>{
    let status=service.rpc("get_status",json!({}))?;
    if status["device"]["id"]!=node{return Err("节点身份已变化，未上传固件".into());}
    let id=uuid::Uuid::new_v4().simple().to_string();
    let call=|method:&str,mut p:Value|{p["lease_token"]=json!(lease);p["job_id"]=json!(id);service.rpc(method,p)};
    let begin=call("firmware.begin",json!({"bytes":data.len(),"sha256":sha}))?;
    if begin["job_id"]!=id||begin["accepted_bytes"]!=0{return Err("节点 OTA 会话不匹配；请查询状态".into());}
    let chunk=begin["chunk_max"].as_u64().ok_or("节点未声明 OTA 分片大小")?.clamp(1,2048) as usize;
    let start=Instant::now();let mut renewed=Instant::now();
    for(offset,bytes)in data.chunks(chunk).enumerate(){
        if renewed.elapsed()>Duration::from_secs(3){service.rpc("control.renew",json!({"lease_token":lease}))?;renewed=Instant::now();}
        let offset=offset*chunk;
        let result=call("firmware.write",json!({"offset":offset,"data_base64":STANDARD.encode(bytes)}))?;
        if result["job_id"]!=id||result["accepted_bytes"].as_u64()!=Some((offset+bytes.len())as u64){return Err("上传确认偏移异常；不会重发，请查询 accepted_bytes".into());}
        if (offset+bytes.len())%65536==0||offset+bytes.len()==data.len(){eprintln!("NODE_OTA_ACCEPTED {}/{}",offset+bytes.len(),data.len());}
        let mut job=service.job.lock().unwrap();job.stage="ota_upload".into();job.done=(offset+bytes.len())as u64;
        job.detail=format!("PSRAM 已接收 {} / {} 字节；尚未切换启动分区",offset+bytes.len(),data.len());
    }
    call("firmware.finish",json!({}))?;
    let deadline=Instant::now()+Duration::from_secs(90);
    loop{
        if renewed.elapsed()>Duration::from_secs(3){service.rpc("control.renew",json!({"lease_token":lease}))?;renewed=Instant::now();}
        let status=service.rpc("firmware.status",json!({}))?;
        if status["job_id"]!=id||status["sha256"]!=sha{return Err("节点 OTA 状态身份不匹配".into());}
        match status["state"].as_str(){
            Some("ready")=>return Ok(json!({"status":status,"elapsed_ms":start.elapsed().as_millis()})),
            Some("writing")=>{
                let mut job=service.job.lock().unwrap();job.stage="ota_write".into();job.done=status["written_bytes"].as_u64().unwrap_or(0);
                job.detail="正在写入备用分区并读回核对，当前启动分区保持有效".into();
            },
            _=>return Err(format!("节点未完成备用分区校验：{}",status["error"].as_str().unwrap_or("状态异常"))),
        }
        if Instant::now()>deadline{return Err("节点写入状态等待超时；请查询状态，不要重复上传".into());}
        std::thread::sleep(Duration::from_millis(300));
    }
}
pub fn start(service:Arc<Service>,path:String,sha:String,node:String,lease:String)->Result<(),String>{
    let _gate=service.operation_gate.lock().unwrap();
    if service.shared.lock().unwrap().is_some(){return Err("请先退出共享调试，再更新节点固件".into());}
    if service.job.lock().unwrap().running||service.target.lock().unwrap().running{return Err("设备任务正在运行，请等待结束".into());}
    if lease.len()!=32||node.len()!=12{return Err("请先连接节点并取得操作权".into());}
    let info=inspect(&path)?;if info["sha256"]!=sha{return Err("文件已变化，请重新选择并确认".into());}
    *service.job.lock().unwrap()=Job{running:true,stage:"ota_upload".into(),total:info["bytes"].as_u64().unwrap(),detail:"准备上传节点 APP，保留网络配置和配对信息".into(),..Default::default()};
    let service=service.clone();
    std::thread::spawn(move||{
        let result=(||{
            let data=std::fs::read(&path).map_err(|e|e.to_string())?;
            if inspect_bytes(&data)?["sha256"]!=sha{return Err("文件在开始前已变化，未上传".into());}
            stage(&service,&data,&sha,&node,&lease)
        })();
        let mut job=service.job.lock().unwrap();job.running=false;
        match result{
            Ok(_)=>{job.stage="ota_ready".into();job.done=job.total;job.detail="备用 APP 已写入并通过完整 SHA256 读回校验，可切换重启".into();},
            Err(e)=>{job.stage="failed".into();job.error=e;job.detail="请读取节点升级状态，核对结果后再继续；没有自动重发".into();},
        }
    });Ok(())
}
#[cfg(test)]
mod tests{
    use super::*;
    fn image()->Vec<u8>{let mut d=vec![0;1024];d[0]=0xe9;d[12]=9;d[32..36].copy_from_slice(&[0x32,0x54,0xcd,0xab]);d[48..53].copy_from_slice(b"0.6.2");d[80..102].copy_from_slice(b"n16r8_wireless_gateway");d[500..519].copy_from_slice(b"MKLINK_NODE_OTA_V1\0");d}
    #[test]fn rejects_other_chip_project_and_missing_boot_confirmation_protocol(){
        let valid=image();assert!(inspect_bytes(&valid).is_ok());
        let mut other=valid.clone();other[12]=13;assert!(inspect_bytes(&other).is_err());
        let mut other=valid.clone();other[80]=b'X';assert!(inspect_bytes(&other).is_err());
        let mut other=valid.clone();other[500]=0;assert!(inspect_bytes(&other).is_err());
        assert!(inspect_bytes(&valid[..500]).is_err());assert!(inspect_bytes(&vec![0;LIMIT+1]).is_err());
    }
}
