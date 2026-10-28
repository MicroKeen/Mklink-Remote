import AdvancedCaptureResult from './AdvancedCaptureResult';
import {useEffect,useRef,useState} from 'react';
import {api,demo} from './client';
import type {DeviceStatus} from './contract';
import SelectControl from './SelectControl';
import {ArtifactInfo,PreparedPlan,TargetIdentity,decodeHex,memoryRead,watchInput,ramWrite,rttInput,type Artifact,type TargetInfo,type TargetJob,type TargetRequest} from './target-contract';
import './target.css';

const phases:Record<string,string>={idle:'等待操作',connecting:'连接目标组件',backup:'备份内部Flash',verify:'逐字节回读核对',preflight_verify:'核对目标是否变化',algorithm_upload:'传送Flash算法',algorithm_upload_verify:'核对算法文件',image_upload:'传送目标镜像',image_upload_verify:'核对镜像文件',program:'烧录APP',complete:'操作完成',failed:'操作停止'};
type Plan=ReturnType<typeof PreparedPlan.parse>;
export default function TargetPanel({status,connected,fresh,job,onRun}:{status:DeviceStatus|null;connected:boolean;fresh:boolean;job:TargetJob;onRun:(request:TargetRequest)=>Promise<void>}){
  const [project,setProject]=useState(()=>localStorage.getItem('mklink-target-project')??(demo?'D:\\Demo\\STM32F411':''));
  const [axf,setAxf]=useState(''),[file,setFile]=useState(''),[artifact,setArtifact]=useState<Artifact|null>(null);
  const [target,setTarget]=useState<TargetInfo|null>(null),[plan,setPlan]=useState<Plan|null>(null),[confirmOpen,setConfirmOpen]=useState(false);
  const [cap,setCap]=useState({binary:false,storage:false}),[error,setError]=useState(''),[launching,setLaunching]=useState(false);
  const [address,setAddress]=useState('0x20000000'),[size,setSize]=useState('16'),[hex,setHex]=useState('');
  const [rttAddr,setRttAddr]=useState(''),[channel,setChannel]=useState('2'),[duration,setDuration]=useState('10'),[input,setInput]=useState('');
  const [watchAddress,setWatchAddress]=useState('0x20000000'),[watchSize,setWatchSize]=useState('36'),[watchPeriod,setWatchPeriod]=useState('0.05');
  const [follow,setFollow]=useState(true),[memory,setMemory]=useState('');
  const dialog=useRef<HTMLDialogElement>(null),terminal=useRef<HTMLPreElement>(null),planButton=useRef<HTMLButtonElement>(null),seen=useRef<unknown>(null);
  const busy=job.running||launching,ready=connected&&fresh&&!!status?.probe?.ready&&cap.binary;
  const enabled=ready&&!!project&&!busy,identified=!!target&&ready;
  useEffect(()=>{setTarget(null);setPlan(null);setMemory('');},[status?.device.id,connected]);
  useEffect(()=>{if(!connected||!fresh||job.running){return;}let alive=true;const read=async()=>{try{const s=await api.rpc('get_probe_transport') as Record<string,unknown>;if(alive)setCap({binary:s.binary_streaming===true,storage:s.storage_ready===true});}catch{if(alive)setCap({binary:false,storage:false});}};void read();const timer=setInterval(()=>void read(),4000);return()=>{alive=false;clearInterval(timer);};},[connected,fresh,job.running,status?.device.id]);
  useEffect(()=>{if(job.running||job.phase!=='complete'||!job.result||seen.current===job.id||(job.action!=='inspect'&&job.node_id!==status?.device.id))return;seen.current=job.id;try{
    if(job.action==='identify')setTarget(TargetIdentity.parse(job.result));
    if(job.action==='inspect'){const a=ArtifactInfo.parse(job.result);setArtifact(a);setPlan(null);if(a.rtt_address)setRttAddr(`0x${a.rtt_address.toString(16)}`);if(/\.(axf|elf)$/i.test(a.path))setAxf(a.path);}
    if(job.action==='prepare_flash'){setPlan(PreparedPlan.parse(job.result));setConfirmOpen(true);}
    if(job.action==='read'){const r=job.result as {address:number;data_hex:string};const rows=r.data_hex.match(/.{1,32}/g)??[];setMemory(rows.map((row,i)=>`0x${(r.address+i*16).toString(16).padStart(8,'0')}  ${row.match(/.{2}/g)?.join(' ')}`).join('\n'));}
  }catch(e){setError(`目标结果格式异常：${String(e)}`);}},[job.running,job.phase,job.action,job.result,job.id,job.node_id,status?.device.id]);
  useEffect(()=>{const d=dialog.current;if(confirmOpen&&!d?.open)d?.showModal();if(!confirmOpen&&d?.open)d.close();},[confirmOpen]);
  const finalChannels=(job.action==='rtt'&&!job.running&&job.result&&typeof job.result==='object'&&'channels' in job.result)?(job.result as {channels:Record<string,string>}).channels:null;
  const terminalText=finalChannels?decodeHex(finalChannels[channel]??''):decodeHex(job.rtt.filter(v=>v.channel===Number(channel)).map(v=>v.data_hex).join(''));
  useEffect(()=>{if(follow&&terminal.current)terminal.current.scrollTop=terminal.current.scrollHeight;},[terminalText,follow]);
  async function run(action:TargetRequest['action'],params:Record<string,unknown>={}){setError('');setLaunching(true);try{
    if(action!=='inspect'&&!project)throw Error('请先选择工程目录，用于保存备份和核验记录');
    if(['rtt','superwatch','rtos_trace'].includes(action)&&!axf.trim())throw Error('请先选择与板上固件匹配的AXF / ELF，用于核验目标RAM范围');
    await onRun({action,node_id:status?.device.id??'',project_root:project,axf:axf||undefined,params});
  }catch(e){setError(String(e));}finally{setLaunching(false);}}
  async function pick(kind:'project'|'firmware'|'symbols'){try{const path=await api.chooseTargetPath(kind);if(!path)return;if(kind==='project'){setProject(path);localStorage.setItem('mklink-target-project',path);setPlan(null);}else if(kind==='symbols')setAxf(path);else{setFile(path);setArtifact(null);setPlan(null);await run('inspect',{artifact:path});}}catch(e){setError(String(e));}}
  function checked(fn:()=>void){try{setError('');fn();}catch(e){setError(String(e));}}
  return <div className="target-workspace">
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">TARGET DEBUGGING</p><h2>STM32F411 目标调试</h2><p>通过当前USB、Wi‑Fi或加密蓝牙连接操作V4后的目标板</p></div><span className={`badge ${ready?'good':'muted'}`}>{ready?'原生通道可用':'等待原生通道'}</span></div><div className="panel-body">
      <div className="target-route" aria-label="目标调试链路"><span>当前管理连接</span><b aria-hidden="true">→</b><span>ESP32-S3</span><b aria-hidden="true">→</b><span>USB2 · V4</span><b aria-hidden="true">→</b><span>SWD · STM32F411</span></div>
      <label className="target-label" htmlFor="target-project">工程目录</label><div className="target-path"><input id="target-project" value={project} disabled={busy} onChange={e=>{setProject(e.target.value);setPlan(null);}} placeholder="选择STM32F411工程目录"/><button disabled={busy} onClick={()=>void pick('project')}>选择目录</button></div><small>备份与核验记录保存在工程的 .mklink/wireless 中。目标任务会独占操作权，结束后回到查看模式。</small>
      <div className="form-actions"><button className="primary" disabled={!enabled} onClick={()=>void run('identify')}>识别目标</button>{target&&<span className="target-identity"><strong>{target.part}</strong><span className="mono">UID {target.uid}</span><span>512 KiB Flash · 128 KiB RAM</span></span>}</div>
      {!ready&&<p className="inline-warn">{!connected?'先连接ESP32-S3。':!fresh?'连接状态已过期，请重新读取。':!status?.probe?.ready?'V4命令通道尚未就绪。':'需要支持原生二进制通道的S3固件0.6.0。'}</p>}
      {error&&<p className="inline-warn" role="alert">{error}</p>}
    </div></section>
    <div className="target-grid">
      <section className="panel"><div className="panel-heading"><div><h2>内存读写</h2><p>读取内部Flash或SRAM；写入仅限SRAM</p></div></div><div className="panel-body">
        <div className="target-fields"><div className="field"><label htmlFor="target-address">地址</label><input id="target-address" className="mono" value={address} disabled={busy} onChange={e=>setAddress(e.target.value)}/></div><div className="field"><label htmlFor="target-read-size">读取字节数</label><input id="target-read-size" inputMode="numeric" value={size} disabled={busy} onChange={e=>setSize(e.target.value)}/></div></div>
        <button disabled={!enabled||!identified} onClick={()=>checked(()=>void run('read',memoryRead(address,size)))}>读取内存</button>
        <div className="field"><label htmlFor="target-write-hex">写入数据 · 十六进制字节</label><textarea id="target-write-hex" className="mono" value={hex} disabled={busy} onChange={e=>setHex(e.target.value)} placeholder="例如 12 34 AB CD" rows={3}/><small>单次最多4096字节。写入可能改变程序行为，完成后会读回比较。</small></div>
        <button disabled={!enabled||!identified||!hex.trim()} onClick={()=>checked(()=>void run('write',{...ramWrite(address,hex),expected_uid:target?.uid}))}>写入RAM并校验</button>
        {memory&&<pre className="target-output mono" tabIndex={0} aria-label="内存读取结果">{memory}</pre>}
      </div></section>
      <section className="panel"><div className="panel-heading"><div><h2>APP 烧录</h2><p>先备份与核对，再确认实际写入镜像</p></div></div><div className="panel-body">
        <label className="target-label" htmlFor="target-firmware">固件文件 · AXF / ELF / 内部APP BIN</label><div className="target-path"><input id="target-firmware" value={file} disabled={busy} onChange={e=>{setFile(e.target.value);setArtifact(null);setPlan(null);}} placeholder="从工程构建产物中选择"/><button disabled={busy} onClick={()=>void pick('firmware')}>选择文件</button></div>
        <div className="form-actions"><button disabled={!file||busy} onClick={()=>void run('inspect',{artifact:file})}>检查文件</button><button className="primary" disabled={!enabled||!identified||!artifact||!cap.storage} onClick={()=>void run('prepare_flash',{artifact:artifact?.path,source_sha256:artifact?.sha256,expected_uid:target?.uid})}>备份并准备烧录</button></div>
        {artifact&&<dl className="target-facts"><dt>内部APP</dt><dd>{artifact.internal_bytes.toLocaleString()} 字节</dd><dt>允许范围</dt><dd className="mono">0x0800C000–0x0807FFFF</dd><dt>源文件SHA256</dt><dd className="mono">{artifact.sha256}</dd><dt>外部资源</dt><dd>{artifact.excluded_external_segments.length?'已排除，不进行写入':'文件不含外部资源段'}</dd></dl>}
        {ready&&!cap.storage&&<p className="inline-warn">V4存储盘尚未挂载，暂不能传送Flash算法和固件。</p>}
        <div className="note-box"><p>保留Bootloader与未覆盖的扇区数据。不会全片擦除、写入外部Flash或修改保护选项。</p></div>
        {plan&&!busy&&<button ref={planButton} onClick={()=>setConfirmOpen(true)}>查看已准备的烧录计划</button>}
      </div></section>
    </div>
    <section className="panel"><div className="panel-heading"><div><h2>RTT 终端</h2><p>一次采集最多30秒，可向目标发送一条下行消息</p></div><span className="mono">CH {channel}</span></div><div className="panel-body">
      <div className="target-path"><div className="field"><label htmlFor="target-symbols">AXF / ELF 符号文件</label><input id="target-symbols" value={axf} disabled={busy} onChange={e=>setAxf(e.target.value)} placeholder="必选；须与板上正在运行的固件匹配"/></div><button disabled={busy} onClick={()=>void pick('symbols')}>选择符号</button></div>
      <div className="target-rtt-fields"><div className="field"><label htmlFor="target-rtt-address">RTT 控制块地址</label><input id="target-rtt-address" className="mono" value={rttAddr} disabled={busy} onChange={e=>setRttAddr(e.target.value)} placeholder="例如从_SEGGER_RTT符号取得"/></div><div className="field"><label htmlFor="target-rtt-channel">通道</label><SelectControl id="target-rtt-channel" value={channel} disabled={busy} onValueChange={setChannel} options={Array.from({length:8},(_,n)=>({value:String(n),label:`CH ${n}`}))}/></div><div className="field"><label htmlFor="target-rtt-duration">采集时长</label><SelectControl id="target-rtt-duration" value={duration} disabled={busy} onValueChange={setDuration} options={[5,10,30].map(n=>({value:String(n),label:`${n} 秒`}))}/></div></div>
      <small>符号文件用于核验目标RAM范围。导入待烧录AXF得到的地址，应在对应固件烧录后使用；通道需由目标实际配置。</small>
      <div className="field"><label htmlFor="target-rtt-input">下行消息 · 可选</label><input id="target-rtt-input" value={input} disabled={busy} onChange={e=>setInput(e.target.value)} placeholder="单次最多256个UTF-8字节；目标需提供该通道的下行缓冲"/></div>
      <div className="form-actions"><button className="primary" disabled={!enabled||!identified||!rttAddr||!axf.trim()} onClick={()=>checked(()=>void run('rtt',{address:rttInput(rttAddr,input),channels:[Number(channel)],duration:Number(duration),input_text:input,input_channel:Number(channel),expected_uid:target?.uid}))}>开始RTT采集</button><button disabled={!job.running||!['rtt','superwatch','rtos_trace','prepare_flash'].includes(job.action)} onClick={()=>void api.stopTarget().catch(e=>setError(String(e)))}>停止采集或准备</button><label className="check"><input type="checkbox" checked={follow} onChange={e=>setFollow(e.target.checked)}/>自动跟随</label></div>
      <pre ref={terminal} className="target-terminal mono" tabIndex={0} aria-label="RTT输出">{terminalText||'等待真实目标RTT数据。'}</pre>
      {job.display_dropped_frames>0&&<small>实时窗口显示最近256片段；结束后的结果保留本次完整有界采集。</small>}
    </div></section>
    <section className="panel"><div className="panel-heading"><div><h2>SuperWatch 与 RTOS Trace</h2><p>连续观察 SRAM 变量与 FreeRTOS 调度，并记录实际速率和丢包统计。</p></div></div><div className="panel-body">
      <div className="target-rtt-fields"><div className="field"><label htmlFor="watch-address">SRAM 变量地址</label><input id="watch-address" className="mono" value={watchAddress} disabled={busy} onChange={e=>setWatchAddress(e.target.value)}/></div><div className="field"><label htmlFor="watch-bytes">采样字节数</label><input id="watch-bytes" value={watchSize} disabled={busy} onChange={e=>setWatchSize(e.target.value)}/></div><div className="field"><label htmlFor="watch-period">采样频率</label><SelectControl id="watch-period" value={watchPeriod} disabled={busy} onValueChange={setWatchPeriod} options={[{value:'0.05',label:'20 Hz'},{value:'0.01',label:'100 Hz'}]}/></div></div>
      <p className="block-hint">复用上方符号文件与采集时长。RTOS Trace 需要目标固件接入 SystemView；并行采集会使用 RTT CH2。</p>
      <div className="form-actions"><button disabled={!enabled||!identified||!axf.trim()} onClick={()=>checked(()=>void run('superwatch',{...watchInput(watchAddress,watchSize),duration:Number(duration),period:Number(watchPeriod),expected_uid:target?.uid}))}>开始 SuperWatch</button><button disabled={!enabled||!identified||!axf.trim()||!rttAddr} onClick={()=>checked(()=>void run('superwatch',{...watchInput(watchAddress,watchSize),duration:Number(duration),period:Number(watchPeriod),rtt_address:rttInput(rttAddr,''),expected_uid:target?.uid}))}>SuperWatch + RTT</button><button disabled={!enabled||!identified||!axf.trim()||!rttAddr} onClick={()=>checked(()=>void run('rtos_trace',{address:rttInput(rttAddr,''),duration:Number(duration),expected_uid:target?.uid}))}>开始 RTOS Trace</button><button disabled={!enabled||!identified} onClick={()=>void run('benchmark',{repetitions:5,expected_uid:target?.uid})}>对比缓冲传输性能</button></div>
      {!job.running&&job.phase==='complete'&&['superwatch','rtos_trace','benchmark'].includes(job.action)&&<AdvancedCaptureResult action={job.action} result={job.result}/>}
    </div></section>
    <section className="panel target-job" aria-live="polite"><div className="panel-body"><strong>{demo?'演示 · ':''}{phases[job.phase]??job.phase}</strong>{job.total>0&&<><progress aria-label="目标操作进度" value={job.done} max={job.total}/><span className="mono">{Math.round(job.done/job.total*100)}%</span></>}{job.error&&<p className="inline-warn">{job.error}</p>}{job.phase==='complete'&&job.action==='write'&&<p>RAM写入与回读一致。</p>}{job.phase==='complete'&&job.action==='verify_flash'&&<p>现有APP完整核对通过，Bootloader与保护选项一致；已复位一次，未重复烧录。</p>}{job.phase==='complete'&&job.action==='flash'&&<p>APP写入与逐字节回读通过，已发出一次复位；请通过RTT或运行变量确认程序运行。</p>}</div></section>
    <dialog ref={dialog} className="target-confirm" aria-labelledby="target-flash-title" onCancel={()=>setConfirmOpen(false)} onClose={()=>{setConfirmOpen(false);requestAnimationFrame(()=>planButton.current?.focus());}}><h2 id="target-flash-title">确认烧录内部 APP</h2><p>请核对这次已备份并准备的目标与镜像。</p>{plan&&<dl className="target-facts"><dt>目标UID</dt><dd className="mono">{plan.target.uid}</dd><dt>写入范围</dt><dd className="mono">0x0800C000–0x0807FFFF</dd><dt>实际镜像SHA256</dt><dd className="mono">{plan.image.sha256}</dd><dt>完整原始备份</dt><dd className="mono">{plan.original_backup}</dd><dt>备份校验</dt><dd>512 KiB独立读回一致</dd></dl>}<p>写入阶段请保持连接与供电。确认后会再次核对目标内容，变化时停止。</p><p>若先前烧录后的校验中断，先恢复V4连接，再选择“仅校验”：完整核对现有APP、Bootloader与保护选项，全部一致后仅复位一次，不重复烧录。</p><div className="form-actions"><button autoFocus onClick={()=>setConfirmOpen(false)}>返回</button><button disabled={busy||!plan||!ready} onClick={()=>{if(!plan)return;setConfirmOpen(false);void run('verify_flash',{plan_path:plan.plan_path,plan_sha256:plan.plan_sha256,confirm:true,expected_uid:plan.target.uid});}}>仅校验已写入APP并复位</button><button className="primary" disabled={busy||!plan||!ready} onClick={()=>{if(!plan)return;setConfirmOpen(false);void run('flash',{plan_path:plan.plan_path,plan_sha256:plan.plan_sha256,confirm:true,expected_uid:plan.target.uid});}}>确认烧录并校验</button></div></dialog>
  </div>;
}
