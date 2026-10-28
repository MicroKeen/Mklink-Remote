import {useEffect,useState} from 'react';
import {api,demo} from './client';
import SelectControl from './SelectControl';
import './target.css';

type Client={id:string;kind:string;name:string;streams:string[]};
type Snapshot={instance_id:string;probe_id:string;transport:string;clients:Client[];busy:boolean;site?:string|null;skill_entry_ready?:boolean};
export default function SharedTargetPanel({nodeId,address,bleAddress,token,beforeAttach,onConnectionChange}:{onConnectionChange:(active:boolean)=>void;nodeId:string;address:string;bleAddress:string;token:string;beforeAttach:()=>Promise<void>}){
  const [node,setNode]=useState(nodeId),[transport,setTransport]=useState('ble');
  const [http,setHttp]=useState(address),[ble,setBle]=useState(bleAddress),[secret,setSecret]=useState(token);
  const [project,setProject]=useState(()=>localStorage.getItem('mklink-target-project')??''),[axf,setAxf]=useState('');
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [memoryAddress,setMemoryAddress]=useState('0x1FFF7A10'),[size,setSize]=useState('12'),[memory,setMemory]=useState('');
  useEffect(()=>{if(nodeId)setNode(nodeId);},[nodeId]);
  useEffect(()=>{if(token)setSecret(token);},[token]);
  useEffect(()=>{if(bleAddress)setBle(bleAddress);},[bleAddress]);
  useEffect(()=>{setHttp(address);},[address]);
  useEffect(()=>{if(snapshot)onConnectionChange(true);},[snapshot?.instance_id]);
  async function run(task:()=>Promise<void>){setBusy(true);setError('');try{await task();}catch(e){setError(String(e));}finally{setBusy(false);}}
  useEffect(()=>{let live=true;void api.sharedControl('status',{}).then(s=>{if(live)setSnapshot(s as Snapshot);}).catch(()=>{});return()=>{live=false;};},[]);
  async function refresh(){setSnapshot(await api.sharedControl('status',{}) as Snapshot);}
  useEffect(()=>{if(!snapshot||busy)return;let live=true;const timer=setInterval(()=>{void api.sharedControl('status',{}).then(s=>{if(live)setSnapshot(s as Snapshot);}).catch(e=>{if(live)setError(String(e));});},4000);return()=>{live=false;clearInterval(timer);};},[!!snapshot,busy]);
  const valid=/^[0-9a-f]{12}$/.test(node)&&/^[0-9a-f]{32}$/.test(secret)&&!!project&&(transport==='http'?!!http:!!ble);
  return <div className="target-workspace shared-target">
    <section className="panel"><div className="panel-heading"><div><h2>共享调试</h2><p>工作台与 AI 技能连接同一台目标，共用采集和任务记录。</p></div><span className={`badge ${snapshot?'good':'muted'}`}>{demo?'演示 · ':''}{snapshot?'已接入':'待接入'}</span></div>
      <div className="panel-body">
        {!snapshot&&<>
        <div className="target-fields"><div className="field"><label htmlFor="shared-node">S3 节点</label><input id="shared-node" disabled={!!snapshot} value={node} onChange={e=>setNode(e.target.value.trim().toLowerCase())} placeholder="12 位节点 ID" autoComplete="off"/></div>
          <div className="field"><label htmlFor="shared-transport">连接方式</label><SelectControl id="shared-transport" disabled={!!snapshot} value={transport} onValueChange={setTransport} options={[{value:'ble',label:'蓝牙'},{value:'http',label:'Wi-Fi / AP 热点'}]}/></div>
          <div className="field"><label htmlFor="shared-address">{transport==='ble'?'蓝牙地址':'设备地址'}</label><input id="shared-address" disabled={!!snapshot} value={transport==='ble'?ble:http} onChange={e=>transport==='ble'?setBle(e.target.value):setHttp(e.target.value)} placeholder={transport==='ble'?'02:00:00:12:34:56':'http://192.168.4.1'}/></div></div>
        <div className="field"><label htmlFor="shared-token">管理密钥</label><input id="shared-token" type="password" autoComplete="off" disabled={!!snapshot} value={secret} onChange={e=>setSecret(e.target.value.trim())}/><small>使用 USB 配对获取的密钥。技能的访问凭据由工作台单独管理。</small></div>
        <div className="field"><label htmlFor="shared-project">目标工程</label><div className="target-path"><input id="shared-project" disabled={!!snapshot} value={project} onChange={e=>setProject(e.target.value)}/><button disabled={busy||!!snapshot} onClick={()=>void run(async()=>{const value=await api.chooseTargetPath('project');if(value)setProject(value);})}>选择目录</button></div></div>
        <div className="field"><label htmlFor="shared-axf">AXF / ELF 符号文件</label><div className="target-path"><input id="shared-axf" disabled={!!snapshot} value={axf} onChange={e=>setAxf(e.target.value)} placeholder="RTT、变量和 Trace 使用与目标固件匹配的文件"/><button disabled={busy||!!snapshot} onClick={()=>void run(async()=>{const value=await api.chooseTargetPath('symbols');if(value)setAxf(value);})}>选择文件</button></div></div>
        </>}
        <div className="form-actions">{!snapshot&&<button className="primary" disabled={busy||!valid} onClick={()=>void run(async()=>{await beforeAttach();const s=await api.sharedControl('attach',{node:{node_id:node,transport,address:transport==='ble'?ble:http,token:secret},project_root:project,axf});setSnapshot(s as Snapshot);localStorage.setItem('mklink-target-project',project);})}>{busy?'处理中…':'接入共享后台'}</button>}
          <button disabled={busy||!snapshot} onClick={()=>void run(async()=>{await api.sharedBrowser();})}>打开调试工作台</button>
          <button disabled={busy||!snapshot} onClick={()=>void run(async()=>{await api.sharedControl('detach',{});setSnapshot(null);onConnectionChange(false);setMemory('');})}>退出本窗口会话</button></div>
        <p className="target-note">调试工作台在浏览器中打开。退出本窗口后，其他已连接的 GUI 和技能会话继续工作。切换 Wi-Fi、热点或蓝牙前，请先结束该节点的所有调试会话。</p>
        {error&&<p className="inline-warn" role="alert">{error}</p>}
      </div></section>
    {snapshot&&<><section className="panel"><div className="panel-heading"><div><h2>当前共享会话</h2><p>在调试工作台中使用 RTT、变量监视、RTOS Trace 和固件烧录。</p></div><button disabled={busy} onClick={()=>void run(refresh)}>刷新</button></div><div className="panel-body"><dl className="target-facts"><dt>后台实例</dt><dd className="mono">{snapshot.instance_id}</dd><dt>无线通道</dt><dd>{snapshot.transport}</dd><dt>技能站点</dt><dd className="mono">{snapshot.skill_entry_ready===false?'尚未配置，请在远程服务中核对访问凭据':snapshot.site??snapshot.probe_id}</dd></dl><ul className="shared-clients">{snapshot.clients.map(c=><li key={c.id}><strong>{c.name}</strong><span>{c.kind} · {c.streams.length?c.streams.join(' / '):'未订阅采集'}</span></li>)}</ul></div></section>
      <section className="panel"><div className="panel-heading"><div><h2>连接核验</h2><p>通过同一后台读取目标内存。</p></div></div><div className="panel-body"><div className="target-fields"><div className="field"><label htmlFor="shared-read-address">地址</label><input id="shared-read-address" value={memoryAddress} onChange={e=>setMemoryAddress(e.target.value)}/></div><div className="field"><label htmlFor="shared-read-size">字节数</label><input id="shared-read-size" type="number" min="1" max="4096" value={size} onChange={e=>setSize(e.target.value)}/></div></div><button disabled={busy} onClick={()=>void run(async()=>{const r=await api.sharedControl('call',{capability:'read_memory',arguments:{address:memoryAddress,size:Number(size)}}) as {data_base64:string};setMemory(Array.from(atob(r.data_base64),x=>x.charCodeAt(0).toString(16).padStart(2,'0')).join(' '));})}>读取</button>{memory&&<pre className="memory-view" aria-label="共享内存读取结果">{memory}</pre>}</div></section></>}
  </div>;
}
