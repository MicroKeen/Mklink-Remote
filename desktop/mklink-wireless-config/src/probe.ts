import type {DeviceStatus} from './contract';
export type ProbeView={label:string;tone:string;ready:boolean;detail:string};
export function probeView(status:DeviceStatus|null,fresh:boolean):ProbeView{
  if(!fresh)return {label:'状态待检查',tone:'muted',ready:false,detail:'重新读取设备状态后再检查探针。'};
  if(!status?.usb.connected)return {label:'未检测到探针',tone:'muted',ready:false,detail:'将 V4 接到黑色 USB-OTG 接口，白色调试口保留供电与日志。'};
  if(status.usb.vid!==0x0d28||status.usb.pid!==0x0202)return {label:'设备类型不匹配',tone:'warn',ready:false,detail:'USB2 检测到其他设备，请连接 Mklink V4。'};
  if(status.usb.invalid_bulk)return {label:'兼容问题待解决',tone:'warn',ready:false,detail:`${status.usb.invalid_bulk} 个 Bulk 端点与当前速度不兼容；请核对 V4 修复固件。`};
  const probe=status.probe;
  if(!probe)return {label:'已枚举 · 需升级 S3',tone:'warn',ready:false,detail:'此 S3 固件只有 USB 枚举能力，更新配套固件后才能验证命令通信。'};
  if(probe.state==='outcome_unknown'||probe.state==='quarantined')return {label:'通信结果待核对',tone:'warn',ready:false,detail:probe.error||'连接已隔离，不会重放请求。核对结果后重新连接 USB2。'};
  if(probe.ready&&probe.state==='ready'&&status.usb.speed==='FULL_12Mbps'&&[8,16,32,64].includes(probe.in_mps)&&[8,16,32,64].includes(probe.out_mps)&&probe.version.trim())return {label:'探针握手通过',tone:'good',ready:true,detail:'已通过命令口身份与版本检查。可执行通信回显；目标芯片与中心业务另行验证。'};
  if(['opening','handshake'].includes(probe.state))return {label:'正在检查探针',tone:'info',ready:false,detail:'正在打开命令接口并核对身份和版本。'};
  return {label:'通信尚未就绪',tone:'warn',ready:false,detail:probe.error||'已完成 USB 枚举，命令口尚未通过检查。'};
}

export function verifyProbeEcho(reply:{reply_base64:string;generation:number},generation:number):void{
  if(reply.generation!==generation)throw Error('探针已重新连接，本次结果不能用于当前连接');
  let raw:string;try{raw=atob(reply.reply_base64);}catch{throw Error('探针回复编码无效');}
  const lines=raw.replaceAll('\r','\n').split('\n').map(line=>line.trim()).filter(Boolean);
  if(lines.at(-1)!=='>>>'||!lines.includes('__mklink_wireless_check__'))throw Error('未收到完整的探针通信回显，不能确认成功');
}
