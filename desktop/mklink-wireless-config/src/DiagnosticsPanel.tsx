import {useEffect,useMemo,useState} from 'react';
import {api,demo} from './client';
import {filterLogs,formatLogs,type LogSnapshot} from './diagnostics';
import './diagnostics.css';
const empty:LogSnapshot={entries:[],total:0,matched:0,dropped:0,counts:{info:0,warning:0,error:0}};
export default function DiagnosticsPanel(){
  const [snapshot,setSnapshot]=useState(empty),[level,setLevel]=useState('all'),[search,setSearch]=useState(''),[paused,setPaused]=useState(false),[notice,setNotice]=useState(''),[error,setError]=useState(''),[exporting,setExporting]=useState(false);
  useEffect(()=>{if(paused)return;let alive=true,running=false;const refresh=async()=>{if(running)return;running=true;try{const next=await api.diagnostics();if(alive){setSnapshot(next);setError('');}}catch(e){if(alive)setError(String(e));}finally{running=false;}};void refresh();const timer=setInterval(()=>void refresh(),3000);return()=>{alive=false;clearInterval(timer);};},[paused]);
  const visible=useMemo(()=>filterLogs(snapshot.entries,level,search),[snapshot,level,search]);
  async function copy(){setError('');try{await navigator.clipboard.writeText(formatLogs(visible));setNotice(`已复制 ${visible.length} 条日志`);}catch{setError('无法访问剪贴板，请使用导出日志。');}}
  async function download(){setExporting(true);setError('');try{const result=await api.exportDiagnostics({level,search,format:'txt'});setNotice(demo?'演示模式：未写入真实文件':`已导出 ${result.entries} 条日志：${result.path}`);}catch(e){setError(String(e));}finally{setExporting(false);}}
  return <section className="diagnostic-panel panel" aria-label="日志诊断">
    <div className="panel-heading"><div><h2>运行日志</h2><p>按级别定位问题，复制或导出当前筛选内容。</p></div><span className="badge">{demo?'演示日志':paused?'已暂停刷新':'每 3 秒刷新'}</span></div>
    <div className="panel-body">
      <div className="diagnostic-filters" role="group" aria-label="日志级别">{([['all','全部',snapshot.total],['info','Info',snapshot.counts.info],['warning','Warning',snapshot.counts.warning],['error','Error',snapshot.counts.error]] as const).map(([id,label,count])=><button key={id} className={`log-filter-${id}`} aria-pressed={level===id} onClick={()=>setLevel(id)}><span className="level-dot"/>{label}<span className="log-count">{count}</span></button>)}</div>
      <div className="diagnostic-toolbar"><div className="diagnostic-search"><label htmlFor="diagnostic-search">搜索日志内容</label><input id="diagnostic-search" placeholder="输入关键词，例如 USB、连接、超时" value={search} onChange={e=>setSearch(e.target.value)}/></div><button onClick={()=>setPaused(v=>!v)}>{paused?'继续刷新':'暂停刷新'}</button><button disabled={!visible.length} onClick={()=>void copy()}>复制日志</button><button className="primary" disabled={!visible.length||exporting} onClick={()=>void download()}>{exporting?'正在导出…':'导出日志'}</button></div>
      <div className="diagnostic-summary"><span>显示 {visible.length} / {snapshot.total} 条</span><span>导出与复制均使用当前筛选条件 · 敏感字段已脱敏</span></div>
      {snapshot.dropped>0&&<p className="inline-warn">缓存最多 5000 条 / 8 MiB；更早的 {snapshot.dropped} 条已移出缓存。</p>}
      {error&&<p role="alert" className="inline-warn">{error}</p>}{notice&&<p role="status" className="diagnostic-notice">{notice}</p>}
      <div className="diagnostic-table-wrap" tabIndex={0} aria-label="日志列表，可滚动"><table className="diagnostic-table"><thead><tr><th scope="col">时间</th><th scope="col">级别</th><th scope="col">来源</th><th scope="col">内容</th></tr></thead><tbody>{visible.map(e=><tr key={e.id}><td className="mono" title={new Date(e.timestamp_ms).toLocaleString('zh-CN',{hour12:false})}>{new Date(e.timestamp_ms).toLocaleTimeString('zh-CN',{hour12:false})}</td><td><span className={`diagnostic-level log-filter-${e.level}`}>{e.level.toUpperCase()}</span></td><td>{e.source}</td><td className="diagnostic-message">{e.message}</td></tr>)}</tbody></table>{!visible.length&&<div className="diagnostic-empty"><strong>{snapshot.total?'没有符合条件的日志':'暂无运行日志'}</strong><p>{snapshot.total?'调整级别或搜索关键词后重试。':'连接设备或执行操作后，日志会显示在这里。'}</p></div>}</div>
    </div>
  </section>;
}
