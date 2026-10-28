import type {DeviceStatus} from './contract';
const bytes=(value:number|undefined)=>value===undefined?'固件未报告':value>=1048576?`${(value/1048576).toFixed(2)} MiB`:`${(value/1024).toFixed(1)} KiB`;
export default function MemoryTelemetry({status}:{status:DeviceStatus|null}){
  if(!status)return null;
  const d=status.device,p=status.probe,b=status.ble;
  return <section className="panel" aria-labelledby="memory-title"><div className="panel-heading"><div><p className="eyebrow">MEMORY & TRANSPORT</p><h2 id="memory-title">内存与传输缓冲</h2><p>PSRAM承载数据缓存；内部RAM保留给DMA、任务栈和控制结构</p></div></div><div className="panel-body"><div className="panel-grid"><dl><dt>PSRAM 容量</dt><dd className="mono">{bytes(d.psram_bytes)}</dd><dt>PSRAM 可用</dt><dd className="mono">{bytes(d.free_psram)}</dd><dt>内部RAM可用</dt><dd className="mono">{bytes(d.free_internal)}</dd><dt>内部最大连续块</dt><dd className="mono">{bytes(d.largest_internal)}</dd></dl><dl><dt>USB 接收缓冲</dt><dd className="mono">{bytes(p?.rx_capacity)}</dd><dt>当前 / 峰值占用</dt><dd className="mono">{bytes(p?.rx_pending)} / {bytes(p?.rx_peak)}</dd><dt>USB 缓冲溢出</dt><dd>{p?.rx_overflows??'固件未报告'}</dd><dt>BLE 发送失败 / 队列等待</dt><dd>{b?.notify_failures??'—'} / {b?.notify_retries??'—'}</dd></dl></div><small>这些数值来自当前设备。缓冲用于吸收突发数据；长期吞吐仍由实际链路和目标采样速率决定。</small></div></section>;
}
