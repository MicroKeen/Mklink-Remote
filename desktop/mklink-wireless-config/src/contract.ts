import { z } from 'zod';
export const NetworkMode=z.enum(['AP','STA','AP+STA']);
export const DeviceConfig=z.object({revision:z.number().int().nonnegative(),last_change_id:z.string(),node_name:z.string(),wifi_ssid:z.string(),password_set:z.boolean(),network_mode:NetworkMode,ap_ssid:z.string(),ap_password_set:z.boolean(),gateway_url:z.string(),gateway_enabled:z.boolean(),bench_id:z.string(),relay_token_set:z.boolean()});
export const Status=z.object({
  device:z.object({id:z.string().min(1),board:z.string(),firmware:z.string(),uptime_ms:z.number().nonnegative(),free_heap:z.number().nonnegative(),psram_bytes:z.number().nonnegative().optional(),free_psram:z.number().nonnegative().optional(),free_internal:z.number().nonnegative().optional(),largest_internal:z.number().nonnegative().optional()}),
  network_mode:NetworkMode,preferred_mode:NetworkMode,switching:z.boolean(),
  wifi:z.object({state:z.enum(['unconfigured','disconnected','connecting','connected']),ssid:z.string(),ip:z.string(),rssi:z.number(),error:z.string()}),
  ap:z.object({active:z.boolean(),ssid:z.string(),ip:z.string(),clients:z.number().int().nonnegative()}),
  usb:z.object({connected:z.boolean(),vid:z.number().int(),pid:z.number().int(),speed:z.string(),invalid_bulk:z.number().int().nonnegative(),interfaces:z.number().int().nonnegative(),endpoints:z.number().int().nonnegative()}),
  probe:z.object({state:z.string(),ready:z.boolean(),version:z.string(),error:z.string(),generation:z.number().int().nonnegative(),in_mps:z.number().int().nonnegative(),out_mps:z.number().int().nonnegative(),rx_pending:z.number().nonnegative().optional(),rx_peak:z.number().nonnegative().optional(),rx_capacity:z.number().nonnegative().optional(),rx_overflows:z.number().nonnegative().optional()}).optional(),
  gateway:z.object({state:z.string(),url:z.string(),control_online:z.boolean(),operations_ready:z.boolean(),error:z.string()}),
  control:z.object({owner:z.string(),busy:z.boolean(),remaining_ms:z.number().nonnegative()}),
  ble:z.object({enabled:z.boolean(),connected:z.boolean(),requests:z.number().nonnegative(),auth_failures:z.number().nonnegative(),notify_retries:z.number().nonnegative().optional(),notify_failures:z.number().nonnegative().optional(),notify_fragments:z.number().nonnegative().optional(),reply_alloc_failures:z.number().nonnegative().optional(),rpc_response_failures:z.number().nonnegative().optional()}).optional(),
});
export const AccessPoints=z.array(z.object({ssid:z.string(),rssi:z.number(),auth:z.string()}));
export type Mode=z.infer<typeof NetworkMode>;
export type DeviceStatus=z.infer<typeof Status>;
export type Config=z.infer<typeof DeviceConfig>;
export type Port={name:string;description:string;vid?:number;pid?:number};
export type BleDevice={address:string;name:string;rssi?:number};
export type InstallJob={running:boolean;stage:string;done:number;total:number;error:string;backup_path:string;detail:string};
export type PairInfo={token:string;ap_ssid:string;ap_password:string;ap_ip:string;port:number};
export type SaveDraft={expected_revision:number;change_id:string;node_name:string;wifi_ssid:string;network_mode:Mode;ap_ssid:string;gateway_url:string;gateway_enabled:boolean;bench_id:string;wifi_password?:string;ap_password?:string;relay_token?:string};
const bytes=(s:string)=>new TextEncoder().encode(s).length;
export function validateDraft(d:SaveDraft):string|null {
  if(Object.values(d).some(v=>typeof v==='string'&&v.includes('\0')))return '配置不能包含空字符';
  if(!d.node_name.trim()||bytes(d.node_name)>63)return '节点名称不能为空，且不能超过 63 字节';
  if(bytes(d.wifi_ssid)>32)return 'Wi-Fi 名称不能超过 32 字节';
  if(d.wifi_password!==undefined&&d.wifi_password!==''&&!(bytes(d.wifi_password)>=8&&bytes(d.wifi_password)<=63)&&!/^[a-fA-F0-9]{64}$/.test(d.wifi_password))return '密码应为 8–63 字节，或 64 位十六进制密钥；开放网络留空';
  if(!d.ap_ssid||bytes(d.ap_ssid)>32)return '热点名称不能为空，且不能超过 32 字节';
  if(d.ap_password!==undefined&&(bytes(d.ap_password)<8||bytes(d.ap_password)>63))return '热点密码应为 8–63 字节';
  if(!NetworkMode.safeParse(d.network_mode).success)return '请选择 AP、STA 或 AP+STA';
  if(bytes(d.gateway_url)>191)return '中心地址过长';
  if(d.gateway_url){try{const u=new URL(d.gateway_url);if(!['ws:','wss:'].includes(u.protocol)||u.username||u.password||u.search||u.hash||u.pathname!=='/')return '中心地址需为 ws(s)://主机:端口，不含路径或凭证';const octets=u.hostname.split('.');const privateIp=octets.length===4&&octets.every(v=>/^\d{1,3}$/.test(v)&&Number(v)<=255)&&(Number(octets[0])===10||Number(octets[0])===127||Number(octets[0])===192&&Number(octets[1])===168||Number(octets[0])===172&&Number(octets[1])>=16&&Number(octets[1])<=31);if(u.protocol==='ws:'&&!privateIp)return '公网中心请使用 wss://；ws:// 仅用于独立测试网络';}catch{return '中心地址需以 ws:// 或 wss:// 开头';}}
  if(bytes(d.bench_id)>63||!/^[-a-zA-Z0-9_.]*$/.test(d.bench_id))return 'Bench ID 仅支持字母、数字、点、下划线和连字符，最多63字节';
  if(d.relay_token!==undefined&&bytes(d.relay_token)>128)return '中心注册令牌不能超过128字节';
  if(d.gateway_enabled&&(!d.gateway_url||!d.bench_id))return '启用中心需要地址和 Bench ID';
  return null;
}
export function wifiQr(ssid:string,password:string):string {const escape=(s:string)=>s.replace(/([\\;,:" ])/g,c=>c===' '?c:'\\'+c);return `WIFI:T:WPA;S:${escape(ssid)};P:${escape(password)};;`;}

export const ProbeTransport=z.object({state:z.string(),generation:z.number().int().nonnegative(),next_sequence:z.number().int().min(1).max(4294967295),framing:z.literal('pika_prompt_v1'),max_request_bytes:z.number().int().positive().max(511),automatic_replay:z.literal(false)});
export const ProbeExchange=z.object({generation:z.number().int().nonnegative(),reply_base64:z.string().max(1400)});
