import type {DeviceStatus} from './contract';
import {probeView} from './probe';
export default function ProbePanel({status,fresh,canCheck,onCheck,onLogs}:{status:DeviceStatus|null;fresh:boolean;canCheck:boolean;onCheck:()=>void;onLogs:()=>void}){
  const view=probeView(status,fresh),probe=status?.probe;
  return <section className="panel" aria-labelledby="probe-heading">
    <div className="panel-heading"><div><h2 id="probe-heading">Mklink 探针</h2><p>USB2 · 分别检查枚举、命令通信与目标业务</p></div><span className={`badge ${view.tone}`}><span className="dot"/>{view.label}</span></div>
    <div className="panel-body">
      <dl><dt>设备标识</dt><dd className="mono">{status?.usb.connected?`${status.usb.vid.toString(16).padStart(4,'0')}:${status.usb.pid.toString(16).padStart(4,'0')}`:'未检测到'}</dd>
        <dt>链路速度</dt><dd className="mono">{status?.usb.connected?status.usb.speed:'—'}</dd>
        <dt>V4 固件</dt><dd>{probe?.version||'握手后显示'}</dd>
        <dt>命令端点</dt><dd>{probe?.in_mps&&probe.out_mps?`IN ${probe.in_mps} / OUT ${probe.out_mps} 字节`:'待检查'}</dd>
        <dt>命令通信</dt><dd>{view.label}</dd></dl>
      <div className={`note-box ${view.tone==='warn'?'warning':''}`}><p>{view.detail}</p></div>
      <small className="block-hint">版本来自本次 USB2 握手。通信检查仅发送探针回显，不读写或复位目标芯片；需要先取得操作权。</small>
      <div className="form-actions" style={{marginTop:18}}><button className="primary" disabled={!canCheck||!view.ready} onClick={onCheck}>检查 V4 通信</button><button onClick={onLogs}>查看诊断日志</button></div>
    </div>
  </section>;
}
