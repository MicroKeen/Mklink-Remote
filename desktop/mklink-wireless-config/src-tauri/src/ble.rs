use aes_gcm::{
    aead::{Aead, KeyInit, Payload},
    Aes128Gcm, Nonce,
};
use btleplug::{
    api::{
        Central, Characteristic, Manager as _, Peripheral as _, ScanFilter, ValueNotification,
        WriteType,
    },
    platform::{Manager, Peripheral},
};
use futures_util::{Stream, StreamExt};
use hmac::{Hmac, Mac};
use serde::Serialize;
use serde_json::Value;
use sha2::Sha256;
use std::{pin::Pin, sync::mpsc, time::Duration};
use uuid::Uuid;
const SERVICE: &str = "9af50001-4c63-4c4d-8b4b-e4790a544401";
const RX: &str = "9af50002-4c63-4c4d-8b4b-e4790a544401";
const TX: &str = "9af50003-4c63-4c4d-8b4b-e4790a544401";
const INFO: &str = "9af50004-4c63-4c4d-8b4b-e4790a544401";
#[cfg(windows)]
async fn negotiated_session(address: &str) -> Option<windows::Devices::Bluetooth::GenericAttributeProfile::GattSession> {
    use windows::Devices::Bluetooth::{BluetoothLEDevice,GenericAttributeProfile::GattSession};
    let address=u64::from_str_radix(&address.replace(':',""),16).ok()?;
    tokio::time::timeout(Duration::from_secs(3),async {
        let device=BluetoothLEDevice::FromBluetoothAddressAsync(address).ok()?.await.ok()?;
        let id=device.BluetoothDeviceId().ok()?;
        GattSession::FromDeviceIdAsync(&id).ok()?.await.ok()
    }).await.ok().flatten()
}
fn fragment_size(pdu: Option<u16>) -> usize {
    // ATT overhead3 + application framing6. Server RX frame capacity256;
    // cap payload240 so framing also fits. Preserve MTU23 support.
    pdu.filter(|n|*n>=23).map(|n|(n as usize-9).min(240)).unwrap_or(14)
}
#[derive(Serialize)]
pub struct Device {
    pub address: String,
    pub name: String,
    pub rssi: Option<i16>,
}
async fn peripherals() -> Result<Vec<Peripheral>, String> {
    let manager = Manager::new().await.map_err(|e| e.to_string())?;
    let mut devices = Vec::new();
    for adapter in manager.adapters().await.map_err(|e| e.to_string())? {
        adapter
            .start_scan(ScanFilter {
                services: vec![Uuid::parse_str(SERVICE).unwrap()],
            })
            .await
            .map_err(|e| e.to_string())?;
        tokio::time::sleep(Duration::from_secs(8)).await;
        for p in adapter.peripherals().await.map_err(|e| e.to_string())? {
            if let Some(properties) = p.properties().await.map_err(|e| e.to_string())? {
                if properties
                    .services
                    .contains(&Uuid::parse_str(SERVICE).unwrap())
                {
                    devices.push(p);
                }
            }
        }
        adapter.stop_scan().await.map_err(|e| e.to_string())?;
    }
    Ok(devices)
}
pub fn list() -> Result<Vec<Device>, String> {
    let runtime = tokio::runtime::Runtime::new().map_err(|e| e.to_string())?;
    runtime.block_on(async {
        let mut result = Vec::new();
        for p in peripherals().await? {
            if let Some(props) = p.properties().await.map_err(|e| e.to_string())? {
                result.push(Device {
                    address: p.address().to_string(),
                    name: props.local_name.unwrap_or_else(|| "Mklink Remote".into()),
                    rssi: props.rssi,
                });
            }
        }
        Ok(result)
    })
}
struct Session {
    peripheral: Peripheral,
    rx: Characteristic,
    info: Characteristic,
    tx_uuid: Uuid,
    notifications: Pin<Box<dyn Stream<Item = ValueNotification> + Send>>,
    key: [u8; 16],
    session_info: Vec<u8>,
    sequence: u32,
    message: u16,
    #[cfg(windows)]
    negotiated: Option<windows::Devices::Bluetooth::GenericAttributeProfile::GattSession>,
}
impl Session {
    async fn open(address: &str, token: &str) -> Result<Self, String> {
        if token.len() != 32 || !token.bytes().all(|v| v.is_ascii_hexdigit()) {
            return Err("请填写 USB 配对取得的32位管理密钥".into());
        }
        let p = peripherals()
            .await?
            .into_iter()
            .find(|p| p.address().to_string().eq_ignore_ascii_case(address))
            .ok_or("未发现所选 Mklink BLE 设备")?;
        p.connect().await.map_err(|e| e.to_string())?;
        p.discover_services().await.map_err(|e| e.to_string())?;
        let chars = p.characteristics();
        let find = |id: &str| {
            chars
                .iter()
                .find(|c| c.uuid == Uuid::parse_str(id).unwrap())
                .cloned()
                .ok_or("设备缺少配置服务特征")
        };
        let info = p.read(&find(INFO)?).await.map_err(|e| e.to_string())?;
        if info.len() != 17 || info[0] != 1 {
            return Err("BLE配置协议不匹配".into());
        }
        let mut secret = [0u8; 16];
        for i in 0..16 {
            secret[i] =
                u8::from_str_radix(&token[i * 2..i * 2 + 2], 16).map_err(|_| "管理密钥格式无效")?;
        }
        let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(&secret).map_err(|e| e.to_string())?;
        mac.update(b"MKLINK-BLE-v1");
        mac.update(&info[1..]);
        let digest = mac.finalize().into_bytes();
        let mut key = [0u8; 16];
        key.copy_from_slice(&digest[..16]);
        secret.fill(0);
        let tx = find(TX)?;
        p.subscribe(&tx).await.map_err(|e| e.to_string())?;
        let notifications = p.notifications().await.map_err(|e| e.to_string())?;
        #[cfg(windows)]
        let negotiated=negotiated_session(address).await;
        #[cfg(windows)]
        eprintln!("BLE_APP_FRAGMENT_BYTES={}",fragment_size(negotiated.as_ref().and_then(|s|s.MaxPduSize().ok())));
        Ok(Self {
            peripheral: p,
            rx: find(RX)?,
            info: find(INFO)?,
            tx_uuid: tx.uuid,
            notifications,
            key,
            session_info: info,
            sequence: 0,
            message: 0,
            #[cfg(windows)]
            negotiated,
        })
    }
    async fn rpc(&mut self, request: Value) -> Result<Value, String> {
        self.sequence = self.sequence.checked_add(1).ok_or("BLE序号耗尽，请重连")?;
        self.message = self.message.wrapping_add(1);
        let seq = self.sequence.to_le_bytes();
        let mut nonce = [0u8; 12];
        getrandom::getrandom(&mut nonce).map_err(|e| e.to_string())?;
        let mut aad = b"mklink-ble-request-v1".to_vec();
        aad.extend(seq);
        let cipher = Aes128Gcm::new_from_slice(&self.key).map_err(|e| e.to_string())?;
        let plain = serde_json::to_vec(&request).map_err(|e| e.to_string())?;
        let encrypted = cipher
            .encrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: &plain,
                    aad: &aad,
                },
            )
            .map_err(|_| "BLE请求加密失败")?;
        let mut packet = seq.to_vec();
        packet.extend(nonce);
        packet.extend(encrypted);
        if packet.len() > 4608 {
            return Err("BLE配置请求过长".into());
        }
        // btleplug0.11 omits MTU; query the existing Windows GATT session.
        // Re-read per RPC in case Windows renegotiates. No long-write guessing.
        #[cfg(windows)]
        let chunk=fragment_size(self.negotiated.as_ref().and_then(|s|s.MaxPduSize().ok()));
        #[cfg(not(windows))]
        let chunk=fragment_size(None);
        let mut response = Vec::new();
        let mut total = 0usize;
        let mut checked_partial = false;
        let result = tokio::time::timeout(Duration::from_secs(30), async {
        for (index, data) in packet.chunks(chunk).enumerate() {
            let mut frame = self.message.to_le_bytes().to_vec();
            frame.extend(((index * chunk) as u16).to_le_bytes());
            frame.extend((packet.len() as u16).to_le_bytes());
            frame.extend(data);
            self.peripheral
                .write(&self.rx, &frame, WriteType::WithResponse)
                .await
                .map_err(|_| "BLE发送失败；结果未知，不自动重发")?;
        }
        let message = self.message;
        let tx = self.tx_uuid;
            loop {
                let next = tokio::time::timeout(Duration::from_millis(250), self.notifications.next()).await;
                let n = match next {
                    Ok(value) => value.ok_or("BLE通知流已关闭")?,
                    Err(_) => {
                        // Some Windows adapters hold the last notification until
                        // another GATT operation. Read existing session metadata
                        // once after a stalled reply, including a single-frame
                        // reply whose first/last notification is held. Never
                        // resend RPC or accept a changed authenticated session.
                        if !checked_partial {
                            checked_partial = true;
                            eprintln!("BLE_REPLY_METADATA_PROBE received={} expected={}",response.len(),total);
                            let info=self.peripheral.read(&self.info).await.map_err(|_| "BLE会话状态读取失败")?;
                            if info!=self.session_info{return Err("BLE会话已变化；结果未知，不自动重发");}
                        }
                        continue;
                    }
                };
                let f = n.value;
                if n.uuid != tx || f.len() < 7 || u16::from_le_bytes([f[0], f[1]]) != message {
                    continue;
                }
                let offset = u16::from_le_bytes([f[2], f[3]]) as usize;
                let length = u16::from_le_bytes([f[4], f[5]]) as usize;
                if offset == 0 {
                    response.clear();
                    total = length;
                }
                if offset != response.len() || length != total || total > 65535 {
                    return Err("BLE响应分帧不一致");
                }
                response.extend_from_slice(&f[6..]);
                if response.len() == total {
                    return Ok(std::mem::take(&mut response));
                }
            }
        })
        .await
        .map_err(|_| format!("BLE响应超时（已收{}/{}字节，会话探测={}）；结果未知，不自动重发",response.len(),total,checked_partial))?
        .map_err(String::from)?;
        if result.len() < 33 || result[..4] != seq {
            return Err("BLE响应序号不符".into());
        }
        let mut aad = b"mklink-ble-response-v1".to_vec();
        aad.extend(seq);
        let plain = cipher
            .decrypt(
                Nonce::from_slice(&result[4..16]),
                Payload {
                    msg: &result[16..],
                    aad: &aad,
                },
            )
            .map_err(|_| "BLE响应认证失败")?;
        serde_json::from_slice(&plain).map_err(|_| "BLE返回无效JSON".into())
    }
}
enum Request {
    Rpc(Value, mpsc::Sender<Result<Value, String>>),
    Close(mpsc::Sender<()>),
}
pub struct Link {
    sender: mpsc::Sender<Request>,
}
impl Link {
    pub fn open(address: String, token: String) -> Result<Self, String> {
        let (sender, receiver) = mpsc::channel::<Request>();
        let (ready_tx, ready_rx) = mpsc::channel();
        std::thread::spawn(move || {
            let runtime = match tokio::runtime::Runtime::new() {
                Ok(r) => r,
                Err(e) => {
                    let _ = ready_tx.send(Err(e.to_string()));
                    return;
                }
            };
            let mut session = match runtime.block_on(Session::open(&address, &token)) {
                Ok(s) => s,
                Err(e) => {
                    let _ = ready_tx.send(Err(e));
                    return;
                }
            };
            let _ = ready_tx.send(Ok(()));
            let mut closed = None;
            for request in receiver {
                match request {
                    Request::Rpc(request, reply) => {
                        let result = runtime.block_on(session.rpc(request));
                        let _ = reply.send(result);
                    }
                    Request::Close(reply) => { closed = Some(reply); break; }
                }
            }
            let _ = runtime.block_on(session.peripheral.disconnect());
            session.key.fill(0);
            if let Some(reply) = closed { let _ = reply.send(()); }
        });
        ready_rx
            .recv_timeout(Duration::from_secs(30))
            .map_err(|_| "BLE连接超时")??;
        Ok(Self { sender })
    }
    pub fn rpc(&self, request: Value) -> Result<Value, String> {
        let (tx, rx) = mpsc::channel();
        self.sender
            .send(Request::Rpc(request, tx))
            .map_err(|_| "BLE会话已结束")?;
        rx.recv_timeout(Duration::from_secs(40))
            .map_err(|_| "BLE结果未知，请重连核对，不自动重发")?
    }
}
impl Drop for Link {
    fn drop(&mut self) {
        let (tx, rx) = mpsc::channel();
        if self.sender.send(Request::Close(tx)).is_ok() {
            // Wait for the worker to release the Windows GATT connection before
            // a reconnect or process exit. Cleanup remains bounded.
            let _ = rx.recv_timeout(Duration::from_secs(5));
        }
    }
}

#[cfg(test)]
mod fragment_tests {
    use super::fragment_size;
    #[test]
    fn fragments_fit_negotiated_att_and_application_header() {
        assert_eq!(fragment_size(None),14);
        assert_eq!(fragment_size(Some(22)),14);
        assert_eq!(fragment_size(Some(23)),14);
        assert_eq!(fragment_size(Some(64)),55);
        assert_eq!(fragment_size(Some(247)),238);
        assert_eq!(fragment_size(Some(517)),240);
    }
}
