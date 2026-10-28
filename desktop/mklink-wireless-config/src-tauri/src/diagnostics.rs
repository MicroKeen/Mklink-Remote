use serde::Serialize;
use serde_json::{json,Value};
use std::{collections::VecDeque,sync::LazyLock,time::{SystemTime,UNIX_EPOCH}};
use regex::Regex;

#[derive(Clone,Serialize)]
pub struct Entry{pub id:u64,pub timestamp_ms:u64,pub level:String,pub source:String,pub message:String}
#[derive(Default)]
pub struct Store{entries:VecDeque<Entry>,next:u64,dropped:u64,bytes:usize}
pub fn redact(text:&str)->String{
    static SECRET:LazyLock<Regex>=LazyLock::new(||Regex::new(r#"(?i)(\b(?:[a-z_]*token|password|ap_password|wifi_password|secret|authorization)\b["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)"#).unwrap());
    static BEARER:LazyLock<Regex>=LazyLock::new(||Regex::new(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+").unwrap());
    let s=BEARER.replace_all(text,"Bearer [REDACTED]");
    SECRET.replace_all(&s,"${1}[REDACTED]").chars().take(4000).collect()
}
pub fn level(text:&str)->&'static str{
    if let Ok(v)=serde_json::from_str::<Value>(text){
        if let Some(level)=v.get("level").or_else(||v.get("levelname")).and_then(Value::as_str){
            return match level.to_ascii_lowercase().as_str(){"error"|"critical"=>"error","warn"|"warning"=>"warning",_=>"info"};
        }
    }
    static PREFIX:LazyLock<Regex>=LazyLock::new(||Regex::new(r"^(?:\[[^\]]+\]\s*)+").unwrap());
    let t=PREFIX.replace(text.trim_start(),"");let u=t.to_ascii_uppercase();
    if u.starts_with("E ")||u.starts_with("ERROR")||u.starts_with("CRITICAL")||text.to_ascii_uppercase().contains("[ERROR]")||t.starts_with("错误"){"error"}
    else if u.starts_with("W ")||u.starts_with("WARN")||text.to_ascii_uppercase().contains("[WARN")||t.starts_with("警告"){"warning"}
    else{"info"}
}
impl Store{
    pub fn push(&mut self,severity:&str,source:&str,message:&str){
        self.next+=1;
        let entry=Entry{id:self.next,timestamp_ms:SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis()as u64,
            level:severity.into(),source:source.into(),message:redact(message)};
        self.bytes+=serde_json::to_vec(&entry).unwrap().len();
        self.entries.push_back(entry);
        while self.entries.len()>5000||self.bytes>8*1024*1024{if let Some(old)=self.entries.pop_front(){self.bytes-=serde_json::to_vec(&old).unwrap().len();self.dropped+=1;}}
    }
    pub fn query(&self,params:&Value)->Result<Value,String>{
        let level=params["level"].as_str().unwrap_or("all");
        if !["all","info","warning","error"].contains(&level){return Err("level must be all/info/warning/error".into());}
        let search=params["search"].as_str().unwrap_or("").to_lowercase();
        let entries:Vec<_>=self.entries.iter().filter(|e|(level=="all"||e.level==level)&&e.message.to_lowercase().contains(&search)).collect();
        Ok(json!({"entries":entries,"total":self.entries.len(),"matched":entries.len(),"dropped":self.dropped,"capacity_bytes":8*1024*1024,
            "counts":{"info":self.entries.iter().filter(|e|e.level=="info").count(),"warning":self.entries.iter().filter(|e|e.level=="warning").count(),"error":self.entries.iter().filter(|e|e.level=="error").count()}}))
    }
}
pub fn text(data:&Value)->String{
    data["entries"].as_array().unwrap().iter().map(|e|format!("{} [{}] [{}] {}",chrono::DateTime::from_timestamp_millis(e["timestamp_ms"].as_i64().unwrap_or(0)).map(|v|v.to_rfc3339_opts(chrono::SecondsFormat::Millis,true)).unwrap_or_default(),e["level"].as_str().unwrap().to_uppercase(),e["source"].as_str().unwrap(),e["message"].as_str().unwrap())).collect::<Vec<_>>().join("\n")
}
#[cfg(test)]mod tests{
    use super::*;
    #[test]fn protects_credentials_and_preserves_hash(){
        let raw=r#"token=abcd password="secret with spaces" lease_token:'abc123' Bearer ey.ab.cd sha256=123456"#;
        let clean=redact(raw);assert!(!clean.contains("abcd"));assert!(!clean.contains("with spaces"));assert!(!clean.contains("abc123"));assert!(!clean.contains("ey.ab.cd"));assert!(clean.contains("sha256=123456"));
    }
    #[test]fn classifies_esp_logs(){assert_eq!(level("I (32) boot: ready"),"info");assert_eq!(level("W (32) usb: retry"),"warning");assert_eq!(level("E (50) ble: failed"),"error");assert_eq!(level(r#"{"levelname":"WARNING","message":"retry"}"#),"warning");assert_eq!(level("[2026-10-28] [pid=42] ERROR: timeout"),"error");}
    #[test]fn limits_serialized_bytes(){let mut s=Store::default();for _ in 0..1000{s.push("info","test",&"\u{0001}".repeat(4000));}let v=s.query(&json!({})).unwrap();assert!(serde_json::to_vec(&v).unwrap().len()<9*1024*1024);assert!(v["dropped"].as_u64().unwrap()>0);}
    #[test]fn filters_counts_and_bounds(){let mut s=Store::default();for _ in 0..5001{s.push("info","node","ready");}s.push("error","agent","link failed token=abc");let v=s.query(&json!({"level":"error","search":"link"})).unwrap();assert_eq!(v["total"],5000);assert_eq!(v["dropped"],2);assert_eq!(v["matched"],1);assert!(!text(&v).contains("abc"));assert!(s.query(&json!({"level":"oops"})).is_err());}
}
