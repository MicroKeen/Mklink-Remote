import AgentHelp from './AgentHelp';
import SelectControl from './SelectControl';
import {useState,type CSSProperties} from 'react';
import type {DeviceStatus,Mode} from './contract';
import './help.css';

type Part='usb1'|'usb2'|'rgb'|'boot'|'rst';
type Topic='board'|'lights'|'buttons'|'start'|'agent';
type Light='ap-wait'|'ap-ready'|'sta-wait'|'sta-ready'|'both-wait'|'both-ready'|'switch'|'fault'|'center';
const parts:Record<Part,{label:string;tag:string;title:string;body:string;note:string}>= {
  usb1:{label:'调试口',tag:'白色线',title:'连接电脑，从这里开始',body:'照片中接白色线、靠近 CH343 芯片的接口。用于供电、安装固件、读取日志与首次配置；请在设备列表选择实际串口。',note:'这是 USB 转串口。串口号可能随电脑变化；请以设备列表为准。'},
  usb2:{label:'USB-OTG',tag:'黑色线',title:'把 Mklink 接到 Host 接口',body:'照片中接黑色线的接口，连接 ESP32-S3 的原生 USB OTG。使用合适的 OTG 连接线接 Mklink V4；电脑维护仍走 USB1。',note:'本板 USB-OTG 焊点用于 5V 供电旁路。设备概览可核对V4版本和通信状态；目标读写、APP烧录与RTT在“目标调试”页面操作。'},
  rgb:{label:'RGB',tag:'状态灯',title:'看这颗方形灯，不看电源灯',body:'靠近 USB2 的大方形灯是可编程 RGB。蓝色表示 AP，绿色表示 STA，紫色表示 AP+STA；闪烁与常亮用于区分等待和就绪。',note:'照片中的小红灯是独立指示灯，不能代替 RGB 判断当前网络模式。'},
  boot:{label:'BOOT',tag:'模式切换',title:'双击切模式，长按回热点',body:'照片中两个按钮的左侧，丝印 BOOT。程序正常启动后，单击不切换；双击在 AP / STA 之间切换，AP+STA 双击回 AP；长按超过3秒后松开回 AP。',note:'切换前释放操作权。按住 BOOT 再复位是 ROM 下载入口，不是普通模式切换。'},
  rst:{label:'RST',tag:'重新启动',title:'重启后，采用已保存的首选模式',body:'照片中两个按钮的右侧，丝印 RST。短按可重启设备。BOOT 的临时切换不会覆盖上位机保存的首选模式。',note:'重启会中断当前连接。安装固件过程中保持供电，等待安装流程完成。'},
};
const lights:Record<Light,{label:string;detail:string;color:string;kind:'blink'|'steady'|'fault'|'center';mode:Mode;condition:string}>= {
  'ap-wait':{label:'AP · 等待直连',detail:'蓝灯慢闪',color:'#287dff',kind:'blink',mode:'AP',condition:'热点已开启，尚无客户端连接。手机或电脑加入设备热点后转为常亮。'},
  'ap-ready':{label:'AP · 已有客户端',detail:'蓝灯常亮',color:'#287dff',kind:'steady',mode:'AP',condition:'至少有一个终端连接设备热点。连接热点后，还需要管理密钥才能使用配置页面。'},
  'sta-wait':{label:'STA · 正在联网',detail:'绿灯慢闪',color:'#45e885',kind:'blink',mode:'STA',condition:'正在连接已保存的 2.4GHz Wi-Fi，尚未获得可用 IP。'},
  'sta-ready':{label:'STA · 已联网',detail:'绿灯常亮',color:'#45e885',kind:'steady',mode:'STA',condition:'已连接路由器并获得 IP。可通过同一局域网管理；中心在线状态单独确认。'},
  'both-wait':{label:'AP+STA · 等待上行',detail:'紫灯慢闪',color:'#bf73ff',kind:'blink',mode:'AP+STA',condition:'设备热点仍可用于维护，STA 上行还没连好。错误密码触发救援热点后，也可能出现此状态。'},
  'both-ready':{label:'AP+STA · 上行就绪',detail:'紫灯常亮',color:'#bf73ff',kind:'steady',mode:'AP+STA',condition:'热点与路由器连接同时开启，STA 已获得 IP。两种管理入口共用同一操作权。'},
  switch:{label:'切换 / 操作提示',detail:'黄色短亮',color:'#ffb337',kind:'steady',mode:'AP',condition:'网络正在切换、长按已达到阈值，或按键切网被操作权阻止。黄色提示本身不代表模式已切换成功。'},
  fault:{label:'无救援 AP 的网络故障',detail:'红灯快闪',color:'#ff5369',kind:'fault',mode:'STA',condition:'发生网络错误，且当前没有救援 AP。救援热点启用后会改用实际模式的灯色；不要要求错误密码时始终红闪。'},
  center:{label:'中心控制通道在线',detail:'模式底色上叠加短白闪',color:'#45e885',kind:'center',mode:'STA',condition:'实际中心注册 / 心跳已确认在线时，每4秒叠加一次短白闪。它不表示 V4 命令或目标烧录已经可用。'},
};
const pins:{id:Part;x:number;y:number;labelX:number;labelY:number}[]=[
  {id:'usb2',x:28,y:36,labelX:15,labelY:12},{id:'usb1',x:28,y:62,labelX:15,labelY:85},
  {id:'rgb',x:46.5,y:38,labelX:56,labelY:12},{id:'boot',x:58,y:61,labelX:54,labelY:85},
  {id:'rst',x:64,y:61,labelX:84,labelY:85},
];

function Board({selected,onSelect,light}:{selected:Part;onSelect:(part:Part)=>void;light:Light}){
  const l=lights[light];
  return <div className="help-board" style={{'--led-color':l.color} as CSSProperties}>
    <div className="board-grid" aria-hidden="true"/>
    <img className="help-board-image" src="/help/board-clean-v2.png" alt="ESP32-S3 N16R8 效果图：白线接调试口，黑线接 USB-OTG，BOOT 在 RST 左侧"/>
    <svg className="board-leaders" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">{pins.map(p=><polyline key={p.id} className={selected===p.id?'selected':''} points={`${p.x},${p.y} ${p.x},${p.labelY} ${p.labelX},${p.labelY}`}/>)}</svg>
    <span className={`board-led ${l.kind}`} aria-hidden="true"/>
    {pins.map(p=><button key={p.id} className={`board-label ${selected===p.id?'selected':''}`} style={{left:`${p.labelX}%`,top:`${p.labelY}%`}} onClick={()=>onSelect(p.id)} aria-label={`查看 ${parts[p.id].label} 说明`} aria-pressed={selected===p.id}><span className="part-dot"/>{parts[p.id].label}<small>{parts[p.id].tag}</small></button>)}
  </div>;
}

export default function HelpPage({status,isDemo=false,onNavigate}:{status:DeviceStatus|null;isDemo?:boolean;onNavigate:(page:string)=>void}){
  const [topic,setTopic]=useState<Topic>('board'),[part,setPart]=useState<Part>('usb1'),[light,setLight]=useState<Light>('ap-wait');
  const [mode,setMode]=useState<Mode>('AP'),[saved,setSaved]=useState<Mode>('AP'),[credentials,setCredentials]=useState(false),[owned,setOwned]=useState(false),[result,setResult]=useState('选择下面的动作，观察示意灯与模式变化。');
  const l=lights[light],p=parts[part];
  function selectPart(id:Part){setPart(id);setTopic('board');}
  function showMode(next:Mode){setMode(next);setLight(next==='AP'?'ap-wait':next==='STA'?'sta-wait':'both-wait');}
  function gesture(action:'single'|'double'|'long'|'reset'){
    if(action==='reset'){const next=saved==='STA'&&!credentials?'AP':saved;showMode(next);setResult(next!==saved?'保存的是 STA，但尚无 STA 凭证 → 启动后保留 AP。':`RST 重启 → 采用已保存的 ${saved}。BOOT 临时切换未覆盖首选模式。`);return;}
    if(action==='single'){setResult('单击 BOOT → 模式不变，避免误触。');return;}
    if(owned){setLight('switch');setResult('拒绝切网：操作权被持有。先释放控制权，再重新按键；不会排队到稍后自动切换。');return;}
    if(action==='long'){showMode('AP');setResult('按住约4秒，达到阈值后松开 → 临时恢复 AP。网络凭证与保存的首选模式保留。');return;}
    if(mode==='AP'&&!credentials){setLight('switch');setResult('尚无 STA 凭证 → 保持 AP。先保存路由器名称和密码，再释放操作权后双击。');return;}
    const next=mode==='AP'?'STA':'AP';showMode(next);setResult(`双击 BOOT → 临时切换到 ${next}。约1.5秒后应用；连接状态仍需单独确认。`);
  }
  return <div className="help-page">
    <div className="help-intro"><div><p className="eyebrow">FIELD GUIDE / N16R8</p><h2>看懂板子，再开始连接。</h2><p>从接口到灯光，把每一次操作与设备状态对应起来。</p></div><span className="help-demo-tag">交互示意 · 不向设备发送命令</span></div>
    <div className="help-tabs" role="tablist" aria-label="帮助主题">{([['board','01','认识接口'],['lights','02','看懂灯光'],['buttons','03','使用按键'],['start','04','开始使用'],['agent','05','Agent 与 CLI']] as const).map(([id,n,label])=><button key={id} role="tab" id={`help-tab-${id}`} aria-controls={`help-panel-${id}`} aria-selected={topic===id} tabIndex={topic===id?0:-1} onKeyDown={e=>{const order:Topic[]=['board','lights','buttons','start','agent'];const i=order.indexOf(topic);const next=e.key==='ArrowRight'?order[(i+1)%5]:e.key==='ArrowLeft'?order[(i+4)%5]:e.key==='Home'?'board':e.key==='End'?'agent':null;if(next){e.preventDefault();setTopic(next);document.getElementById(`help-tab-${next}`)?.focus();}}} onClick={()=>setTopic(id)}><span>{n}</span>{label}</button>)}</div>
    <section role="tabpanel" id={`help-panel-${topic}`} aria-labelledby={`help-tab-${topic}`} className="help-topic">
      {topic==='agent'?<AgentHelp/>:topic!=='start'?<div className="help-visual-grid"><div className="help-photo-panel"><div className="help-photo-top"><span>ESP32-S3 · N16R8</span><span>实物定位 / 状态效果</span></div><Board selected={part} onSelect={selectPart} light={light}/><div className="help-photo-bottom"><span className={`help-led-swatch ${l.kind}`} style={{'--led-color':l.color} as CSSProperties}/><div><strong>{l.detail}</strong><small>示意：{l.label} · 以设备实际状态为准</small></div><span className="mono">{topic==='buttons'?mode:l.mode}</span></div><p className="help-photo-credit">基于实物照片整理的效果图。白色线为调试口，黑色线为 USB-OTG；效果图用于接口定位，不作为引脚接线依据。<a href="/help/board-source.jpg" target="_blank" rel="noreferrer">查看原始实物照片 ↗</a></p></div>
      <div className="help-explanation">
        {topic==='board'&&<><p className="eyebrow">HARDWARE / {p.label}</p><div className="help-part-switch" aria-label="板卡部位">{(Object.keys(parts) as Part[]).map(id=><button key={id} className={part===id?'on':''} onClick={()=>setPart(id)} aria-pressed={part===id}>{parts[id].label}</button>)}</div><h3>{p.title}</h3><p>{p.body}</p><div className="help-callout">{p.note}</div><div className="help-next"><span>下一步</span><button onClick={()=>setTopic(part==='rgb'?'lights':part==='boot'||part==='rst'?'buttons':'start')}>{part==='rgb'?'查看灯效演示':part==='boot'||part==='rst'?'演示按键逻辑':'查看连接步骤'} <span aria-hidden="true">→</span></button></div></>}
        {topic==='lights'&&<><p className="eyebrow">LIGHT / STATE</p><h3>颜色看模式，闪烁看进度。</h3><p>选择一种状态，看板上的方形 RGB 如何表示它。</p><div className="help-light-picker" aria-label="灯效状态">{(Object.keys(lights) as Light[]).map(id=><button key={id} aria-pressed={light===id} className={light===id?'on':''} onClick={()=>{setLight(id);setPart('rgb');}}><i style={{background:lights[id].color}}/>{lights[id].label}</button>)}</div><div className="help-state-detail" aria-live="polite"><strong>{l.detail}</strong><p>{l.condition}</p></div><small className="help-footnote">慢闪约0.6秒亮 / 0.6秒灭。中心短白闪在演示中延长，便于观察；白闪不代表 V4 业务就绪。动效会尊重系统的“减少动态效果”设置。</small></>}
        {topic==='buttons'&&<><p className="eyebrow">BOOT / TRY IT</p><h3>先释放操作权，再按 BOOT。</h3><p>这里是本地演示。修改模拟条件，看看为什么有时按键不会切网。</p><div className="help-sim-fields"><label>模拟当前模式<SelectControl aria-label="模拟当前模式" value={mode} onValueChange={v=>showMode(v as Mode)} options={['AP','STA','AP+STA'].map(v=>({value:v,label:v}))}/></label><label>已保存的首选模式<SelectControl aria-label="模拟已保存模式" value={saved} onValueChange={v=>setSaved(v as Mode)} options={['AP','STA','AP+STA'].map(v=>({value:v,label:v}))}/></label></div><label className="check"><input type="checkbox" checked={credentials} onChange={e=>setCredentials(e.target.checked)}/>模拟：已保存 STA 名称与密码</label><label className="check"><input type="checkbox" checked={owned} onChange={e=>setOwned(e.target.checked)}/>模拟：操作权正被持有</label><div className="help-gesture-buttons"><button onClick={()=>gesture('single')}>单击 BOOT</button><button onClick={()=>gesture('double')}>双击 BOOT</button><button onClick={()=>gesture('long')}>长按4秒并松开</button><button onClick={()=>gesture('reset')}>RST 复位</button></div><div className="help-state-detail" role="status"><strong>模拟结果 · 当前 {mode}</strong><p>{result}</p></div><small className="help-footnote">双击的两次点击间隔约0.4秒内。长按是在松开时执行。按住 BOOT 再复位会进入 ROM 下载模式，区别于此处的运行时手势。</small></>}
      </div></div>:<div className="help-start"><div className="help-start-heading"><h3>首次使用，沿着这条路径走。</h3><p>出厂固件从第一步开始；已安装无线固件可从第二步开始。</p></div><ol className="help-journey">{[
        ['安装默认固件','USB1 接电脑，选择正确串口。上位机先完整备份，再写入并校验。','install'],
        ['读取连接信息','通过 USB1 读取热点名称、随机热点密码及管理密钥。两种凭证用途不同。','network'],
        ['选择管理入口','热点直连、局域网或 BLE。首次 BLE 配置使用 USB1 取得的管理密钥。','overview'],
        ['取得操作权，再保存','查看状态无需独占；配置前取得操作权。保存后按需要应用网络，再核对状态。','network'],
      ].map(([title,body,target],i)=><li key={title}><span className="help-step-number">{String(i+1).padStart(2,'0')}</span><div><h4>{title}</h4><p>{body}</p><button onClick={()=>onNavigate(target)}>前往{target==='install'?'安装页面':target==='network'?'网络与热点':'设备概览'} <span aria-hidden="true">→</span></button></div></li>)}</ol><div className="help-route-grid"><article><span>AP</span><h4>手机 / 电脑直连</h4><p>加入 MklinkRemote-XXXXXX 热点 → 扫管理码或打开热点地址 → 输入管理密钥。热点密码只用于加入 Wi-Fi。</p></article><article><span>STA / AP+STA</span><h4>接入现有局域网</h4><p>保存2.4GHz Wi-Fi凭证并应用 → 等待取得IP → 在同一局域网管理。AP+STA保留热点维护入口。</p></article><article><span>BLE</span><h4>近距离无线配置</h4><p>USB1取得管理密钥 → 扫描 Mklink 节点 → 建立加密配置连接。无需切换电脑当前使用的 Wi-Fi。</p></article></div><div className="help-callout"><strong>调试目标板：识别 → 读写 → 准备 → 核对 → 烧录 → RTT</strong><p>先确认目标板供电与SWD接线，再选择工程目录并识别目标。内存直接写入只允许SRAM。烧录前读取并独立核对完整内部Flash备份，确认目标UID和镜像SHA256后才开始写入；RTT地址和符号文件应与板上固件一致。</p><button onClick={()=>onNavigate('target')}>前往目标调试 →</button></div><div className="help-callout"><strong>中心在线与 V4 可操作，分别确认。</strong><p>中心依赖 STA 上行，沿用注册与心跳协议。USB枚举、网络联网或白色心跳提示，都不能代替真实 Mklink 业务验证。</p></div></div>}
    </section>
    <div className="help-live-note"><span className="part-dot"/><div><strong>{status?(isDemo?'演示设备状态':'当前设备返回的状态'):'实际设备状态单独查看'}</strong><p>{status?`设备 ${status.device.id} · ${status.network_mode} · ${status.control.owner?'操作权被持有':'操作权空闲'}。上方灯效始终是演示。`:'本页无需连接设备即可使用。实际模式、IP、操作权和 V4 状态请到设备概览核对。'}</p></div><button onClick={()=>onNavigate('overview')}>查看设备概览 →</button></div>
  </div>;
}
