export default function AdvancedCaptureResult({action,result}:{action:string;result:unknown}){
  if(!result||typeof result!=='object')return null;
  const data=result as Record<string,unknown>;
  const number=(v:unknown,digits=1)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:digits}):'—';
  const stats=(data.stats&&typeof data.stats==='object'?data.stats:{}) as Record<string,unknown>;
  const metrics=action==='rtos_trace'?[
    ['调度事件',number(data.events,0)],['接收事件率',`${number(data.events_s)} /s`],['丢失数据包',number(data.dropped_packets,0)],['解码同步',data.synced?'已同步':'未同步'],
  ]:[['采样数量',number(data.samples,0)],['接收采样率',`${number(data.received_samples_s)} Hz`],['目标采样率',`${number(data.target_samples_s)} Hz`],['丢失采样',number(stats.parser_dropped_frames,0)]];
  const cases=Array.isArray(data.cases)?data.cases as Record<string,unknown>[]:[];
  return <div className="capture-result" aria-label="高级采集结果" aria-live="polite">
    {action==='benchmark'?<div className="capture-table"><table><caption>同一段目标 Flash 的传输对比</caption><thead><tr><th>读取窗口</th><th>读取中位耗时</th><th>95% 耗时</th><th>有效吞吐</th></tr></thead><tbody>{cases.map((row,i)=><tr key={i}><td>{number(row.window_bytes,0)} B</td><td>{number(row.p50_ms)} ms</td><td>{number(row.p95_ms)} ms</td><td>{typeof row.goodput_bytes_s==='number'?number(row.goodput_bytes_s/1024):'—'} KiB/s</td></tr>)}</tbody></table></div>:<div className="capture-metrics">{metrics.map(([name,value])=><div key={name}><span>{name}</span><strong>{value}</strong></div>)}</div>}
    {action==='rtos_trace'&&!!data.task_names&&typeof data.task_names==='object'&&<p>已识别任务：{Object.values(data.task_names).map(String).join('、')||'本次未收到任务名称，请检查目标 Trace 配置'}</p>}
    {typeof data.capture_path==='string'&&<p className="capture-path">采集记录：<span className="mono">{data.capture_path}</span></p>}
    <details><summary>查看完整统计</summary><pre className="target-terminal mono" tabIndex={0}>{JSON.stringify(result,null,2)}</pre></details>
  </div>;
}
