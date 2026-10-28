import type {LogSnapshot} from './diagnostics';
import {TargetJobSchema,emptyTargetJob,type TargetJob,type TargetRequest} from './target-contract';
import {NodeImage,NodeUpdate,type NodeUpdateInfo} from './node-firmware';
import {invoke,isTauri} from '@tauri-apps/api/core';
import {AccessPoints,DeviceConfig,Status,validateDraft,type Config,type DeviceStatus,type InstallJob,type Port,type SaveDraft,type PairInfo,type BleDevice} from './contract';
export const demo=!isTauri()&&new URLSearchParams(location.search).get('demo')==='1';
let config:Config={revision:1,last_change_id:'',node_name:'现场无线节点',wifi_ssid:'',password_set:false,network_mode:'AP',ap_ssid:'MklinkRemote-123456',ap_password_set:true,gateway_url:'',gateway_enabled:false,bench_id:'s3-020000123456',relay_token_set:false};
let connected=false,bleConnected=false,leaseToken='',owner='',apPassword='Demo-Only-4826',actualMode:Config['network_mode']='AP';
const probeScenario=new URLSearchParams(location.search).get('probe')??'ready';
let probeSequence=0;
let wifiState:DeviceStatus['wifi']['state']='unconfigured';
let job:InstallJob={running:false,stage:'idle',done:0,total:0,error:'',backup_path:'',detail:''};
let targetJob:TargetJob={...emptyTargetJob};
const demoTarget={part:'STM32F411CEUx',uid:'00112233445566778899aabb',debug_id:'0x10006431',flash_bytes:524288,option_control:'0x0fffaaed'};
let sharedDemoConnected=false;
let demoArtifact:Record<string,unknown>={};
let demoOta:NodeUpdateInfo={protocol:1,state:'idle',job_id:'',sha256:'',version:'',error:'',bytes:0,accepted_bytes:0,written_bytes:0,chunk_max:2048,image_max:4194304,running_slot:'factory',running_version:'0.7.2-demo',destination_slot:'',health_ready:true,busy:false,confirm_remaining_ms:0};

async function call<T>(name:string,args?:Record<string,unknown>):Promise<T>{
  if(!isTauri())throw Error('真实连接请使用桌面上位机；浏览器预览不会操作硬件');
  if(name==='choose_target_path')return invoke<T>(name,args);
  if(name==='shared_browser')return invoke<T>('agent_open_browser');
  return invoke<T>('agent_call',{method:name,params:args??{}});
}
export const api={
  serviceStatus:async():Promise<{management:{connected:boolean;transport:'usb'|'lan'|'ble'|'none';revision:number}|null;shared:boolean|null}>=>call('service_status'),
  preferences:async(params?:Record<string,string>):Promise<{theme:string;skin:string;page:string;revision:number}>=>call(params?'preferences_set':'preferences_get',params),
  diagnostics:async():Promise<LogSnapshot>=>demo?{entries:[{id:1,timestamp_ms:1793145600000,level:'info',source:'device',message:'I CONFIG_READY · 演示：节点配置接口已就绪'},{id:2,timestamp_ms:1793145601000,level:'warning',source:'device',message:'W USB · 演示：USB2 连接曾断开，请检查 OTG 接线'},{id:3,timestamp_ms:1793145602000,level:'error',source:'agent',message:'E BLE · 演示：请求超时，结果未知；请查询状态，不自动重发'},{id:4,timestamp_ms:1793145603000,level:'info',source:'agent',message:'共享后台已接入 · token=[REDACTED]'}],total:4,matched:4,dropped:0,counts:{info:2,warning:1,error:1}}:call('diagnostics_query'),
  exportDiagnostics:async(params:{level:string;search:string;format:string}):Promise<{path:string;entries:number}>=>demo?{path:'演示模式',entries:0}:call('diagnostics_export',params),
  sharedControl:async(method:string,params:Record<string,unknown>):Promise<unknown>=>{
    if(!demo)return call('shared_control',{method,params});
    if(method==='attach')sharedDemoConnected=true;
    if(method==='status'&&!sharedDemoConnected)throw Error('未接入');
    if(method==='call')return {data_base64:btoa('DEMO-ONLY-UID')};
    if(method==='detach'){sharedDemoConnected=false;return {detached:true};}
    return {instance_id:'demo-shared-backend',probe_id:'s3-demo-node',transport:'s3-ble',site:'demo-only',skill_entry_ready:true,busy:false,clients:[{id:'demo-gui',kind:'sdk',name:'无线工作台 · 演示',streams:[]},{id:'demo-ai',kind:'sdk',name:'AI 技能 · 演示',streams:['rtt']}]};
  },
  sharedBrowser:async():Promise<void>=>{if(!demo)await call('shared_browser');},
  ports:async():Promise<Port[]>=>demo?[{name:'COM16',description:'CH343 · 演示设备',vid:0x1a86,pid:0x55d3}]:call('list_ports'),
  connectSerial:async(port:string)=>{if(demo){connected=true;return;}await call('connect_serial',{port});},
  connectLan:async(url:string,token:string)=>{if(demo){connected=true;return;}await call('connect_lan',{url,token});},
  bleDevices:async():Promise<BleDevice[]>=>demo?[{address:'02:00:00:12:34:56',name:'MklinkRemote-123456',rssi:-56}]:call('list_ble'),
  connectBle:async(address:string,token:string)=>{if(demo){if(!address||!/^[0-9a-f]{32}$/i.test(token))throw Error('请选择蓝牙节点并填写32位管理密钥');connected=true;bleConnected=true;return;}await call('connect_ble',{address,token});},
  disconnect:async()=>{if(demo){connected=false;bleConnected=false;return;}await call('disconnect');},
  rpc:async(method:string,params:Record<string,unknown>={}):Promise<unknown>=>{
    if(!demo)return call('rpc',{method,params});if(!connected)throw Error('设备未连接');await new Promise(r=>setTimeout(r,70));
    if(method==='get_config')return {...config};
    if(method==='firmware.status')return {...demoOta};
    if(['firmware.claim','firmware.activate','firmware.confirm','firmware.abort'].includes(method)){
      if(!owner||params.lease_token!==leaseToken)throw Error('请先取得操作权');
      if(params.job_id!==demoOta.job_id)throw Error('升级任务不匹配');
      if(method==='firmware.claim'&&params.sha256!==demoOta.sha256)throw Error('镜像摘要不匹配');
      if(method==='firmware.activate'){if(demoOta.state!=='ready')throw Error('备用固件未就绪');demoOta={...demoOta,state:'pending_verify',running_slot:'ota_0',running_version:demoOta.version,confirm_remaining_ms:120000,busy:true};owner='';leaseToken='';}
      if(method==='firmware.confirm'){if(demoOta.state!=='pending_verify')throw Error('未处于新版本确认阶段');demoOta={...demoOta,state:'confirmed',busy:false,confirm_remaining_ms:0};}
      if(method==='firmware.abort')demoOta={...demoOta,state:'aborted',busy:false};
      return {...demoOta};
    }
    if(method==='get_status')return {device:{id:'020000123456',board:'ESP32-S3 N16R8',firmware:'0.7.2-demo',uptime_ms:162000,free_heap:4959140,psram_bytes:8388608,free_psram:4925320,free_internal:33807,largest_internal:21504},network_mode:actualMode,preferred_mode:config.network_mode,switching:false,wifi:{state:wifiState,ssid:config.wifi_ssid,ip:wifiState==='connected'?'192.168.50.20':'',rssi:-48,error:''},ap:{active:actualMode!=='STA',ssid:config.ap_ssid,ip:actualMode!=='STA'?'192.168.4.1':'',clients:actualMode!=='STA'?1:0},usb:{connected:true,vid:3368,pid:514,speed:'FULL_12Mbps',invalid_bulk:probeScenario==='legacy'?10:0,interfaces:8,endpoints:13},...(probeScenario==='old-s3'?{}:{probe:{state:probeScenario==='quarantined'?'outcome_unknown':probeScenario==='opening'?'opening':'ready',ready:probeScenario==='ready',version:probeScenario==='ready'?'演示版本（非设备实测）':'',error:probeScenario==='quarantined'?'演示：回复中断，结果待核对':'',generation:2,in_mps:64,out_mps:64,rx_capacity:3145728,rx_pending:0,rx_peak:16384,rx_overflows:0}}),gateway:{state:config.gateway_enabled&&wifiState==='connected'?'control_online':config.gateway_enabled?'waiting_network':'disabled',url:config.gateway_url,control_online:config.gateway_enabled&&wifiState==='connected',operations_ready:false,error:''},control:{owner,busy:false,remaining_ms:owner?15000:0},ble:{enabled:true,connected:bleConnected,requests:12,auth_failures:0,notify_retries:0,notify_failures:0}};
    if(method==='get_probe_transport')return {state:probeScenario==='ready'?'ready':'driver_unbound',generation:2,next_sequence:probeSequence+1,max_payload:1024,max_request_bytes:511,framing:'pika_prompt_v1',automatic_replay:false,binary_streaming:probeScenario==='ready',storage_ready:probeScenario==='ready'};
    if(method==='probe.exchange'){
      if(!owner||params.lease_token!==leaseToken)throw Error('请先取得控制权');
      if(probeScenario!=='ready'||params.generation!==2||Number(params.sequence)<=probeSequence)throw Error('连接已变化或请求重复，未执行');
      if(params.request_base64!==btoa("print('__mklink_wireless_check__')\n"))throw Error('演示只支持通信回显');
      probeSequence=Number(params.sequence);return {generation:2,reply_base64:btoa('__mklink_wireless_check__\r\n>>> ')};
    }
    if(method==='pair')return {token:'00000000000000000000000000000000',ap_ssid:config.ap_ssid,ap_password:apPassword,ap_ip:'192.168.4.1',port:80} satisfies PairInfo;
    if(method==='scan_wifi')return [{ssid:'C6-Mklink-Test',rssi:-42,auth:'WPA2'},{ssid:'Workshop-2.4G',rssi:-67,auth:'WPA2/WPA3'}];
    if(method==='get_logs')return ['I CONFIG_READY · 演示数据','I AP MklinkRemote-123456 · 等待现场连接',probeScenario==='legacy'?'W V4 Bulk MPS=512，Full-Speed 通信待验证':'W 演示事件：USB2 连接曾断开'];
    if(method==='control.acquire'){if(owner)throw Error('操作权已被其他终端持有');owner=String(params.owner);leaseToken=crypto.randomUUID().replaceAll('-','');return {lease_token:leaseToken,ttl_ms:15000};}
    if(method==='control.renew'||method==='control.release'){if(!owner||params.lease_token!==leaseToken)throw Error('操作权已失效');if(method==='control.release'){owner='';leaseToken='';}return {ttl_ms:15000};}
    if(method==='set_config'||method==='apply_network'||method==='connect_wifi'){
      if(!owner||params.lease_token!==leaseToken)throw Error('请先取得控制权');
      if(method==='set_config'){const p=params as unknown as SaveDraft;if(config.last_change_id===p.change_id)return {...config};if(p.expected_revision!==config.revision)throw Error('配置已变更，请重新读取');const invalid=validateDraft(p);if(invalid)throw Error(invalid);if(p.ap_password!==undefined)apPassword=p.ap_password;config={revision:config.revision+1,last_change_id:p.change_id,node_name:p.node_name,wifi_ssid:p.wifi_ssid,password_set:p.wifi_password===undefined?config.password_set:!!p.wifi_password,network_mode:p.network_mode,ap_ssid:p.ap_ssid,ap_password_set:true,gateway_url:p.gateway_url,gateway_enabled:p.gateway_enabled,bench_id:p.bench_id,relay_token_set:p.relay_token===undefined?config.relay_token_set:!!p.relay_token};return {...config};}
      actualMode=config.network_mode;wifiState=actualMode!=='AP'&&config.wifi_ssid?'connected':'unconfigured';return {accepted:true,apply_after_ms:1500};
    }
    throw Error('该能力尚未就绪');
  },
  status:async()=>Status.parse(await api.rpc('get_status')),
  config:async()=>DeviceConfig.parse(await api.rpc('get_config')),
  scan:async(lease:string)=>AccessPoints.parse(await api.rpc('scan_wifi',{lease_token:lease})),
  logs:async():Promise<string[]>=>{const value=await api.rpc('get_logs');if(!Array.isArray(value)||value.some(line=>typeof line!=='string'))throw Error('节点日志格式无效');return value as string[];},
  exportLogs:async():Promise<string>=>demo?'演示模式未写入真实文件':call('export_logs'),
  startInstall:async(port:string)=>{if(demo){job={running:false,stage:'complete',done:100,total:100,error:'',backup_path:'演示备份路径',detail:'演示安装完成；未操作硬件'};return;}await call('start_install',{port});},
  installJob:async():Promise<InstallJob>=>demo?job:call('install_job'),
  exportFirmware:async():Promise<string>=>demo?'演示模式未写入真实文件':call('export_firmware'),
  chooseNodeFirmware:async():Promise<string|null>=>demo?'D:\\Demo\\MklinkRemote-0.6.2.bin':call('choose_target_path',{kind:'node_firmware'}),
  inspectNodeFirmware:async(path:string)=>NodeImage.parse(demo?{path,bytes:1384320,sha256:'a'.repeat(64),version:'0.7.2-demo',project:'n16r8_wireless_gateway'}:await call('inspect_node_firmware',{path})),
  nodeUpdateStatus:async()=>NodeUpdate.parse(await api.rpc('firmware.status')),
  startNodeUpdate:async(path:string,sha:string,node:string,lease:string)=>{
    if(!demo){await call('start_node_update',{path,sha,node,lease});return;}
    if(!owner||lease!==leaseToken)throw Error('请先取得操作权');
    demoOta={...demoOta,state:'ready',job_id:crypto.randomUUID().replaceAll('-',''),sha256:sha,version:'0.7.2-demo',bytes:1384320,accepted_bytes:1384320,written_bytes:1384320,destination_slot:'ota_0',busy:true};
    job={running:false,stage:'ota_ready',done:1384320,total:1384320,error:'',backup_path:'',detail:'演示：备用 APP 已就绪；未操作硬件'};
  },
  chooseTargetPath:async(kind:'project'|'firmware'|'symbols'):Promise<string|null>=>demo?(kind==='project'?'D:\\Demo\\STM32F411':kind==='symbols'?'D:\\Demo\\STM32F411\\APP.axf':'D:\\Demo\\STM32F411\\APP.axf'):call('choose_target_path',{kind}),
  targetJob:async():Promise<TargetJob>=>demo?structuredClone(targetJob):TargetJobSchema.parse(await call('target_job')),
  stopTarget:async()=>{if(demo){targetJob={...targetJob,running:false,phase:'failed',error:'演示任务已停止，未操作硬件'};owner='';return;}await call('stop_target');},
  startTarget:async(request:TargetRequest)=>{
    if(!demo){await call('start_target',{request});return;}
    if(targetJob.running)throw Error('目标任务正在运行');
    if(request.action!=='inspect'&&!connected)throw Error('设备未连接');
    const id=crypto.randomUUID();targetJob={...emptyTargetJob,id,node_id:request.node_id,running:true,action:request.action,phase:request.action==='prepare_flash'?'backup':'connecting'};
    const result=()=>{
      const p=request.params;
      if(request.action==='inspect'){demoArtifact={path:String(p.artifact),sha256:'1'.repeat(64),internal_bytes:411816,base:0x0800c000,end:0x08080000,excluded_external_segments:[{address:0x90000000,bytes:188416}],rtt_address:0x20019d98};return demoArtifact;}
      if(request.action==='benchmark')return {demo:true,readonly:true,repetitions:5,cases:[{window_bytes:1024,p50_ms:2700,goodput_bytes_s:1515},{window_bytes:4096,p50_ms:1532,goodput_bytes_s:2686}]};
      if(request.action==='superwatch')return {demo:true,native_push:true,host_memory_polling:false,samples:Math.round(Number(p.duration)/Number(p.period)),distinct_values:100,requested_hz:1/Number(p.period),received_samples_s:.99/Number(p.period),target_samples_s:1/Number(p.period),stats:{parser_dropped_frames:0,parser_crc_errors:0},capture_path:'D:\\Demo\\superwatch.jsonl'};
      if(request.action==='rtos_trace')return {demo:true,rtos:'FreeRTOS',events:2400,events_s:240,synced:true,task_names:{'0x20001000':'WirelessHIL'},dropped_bytes:0,dropped_packets:0,capture_path:'D:\\Demo\\rtos-trace.jsonl'};
      if(request.action==='identify')return demoTarget;
      if(request.action==='read')return {target:demoTarget,address:p.address,bytes:p.size,data_hex:'12345678'.repeat(Math.ceil(Number(p.size)/4)).slice(0,Number(p.size)*2)};
      if(request.action==='write')return {target:demoTarget,address:p.address,bytes:String(p.data_hex).length/2,verified:true};
      if(request.action==='prepare_flash')return {state:'PREPARED',target:demoTarget,source:demoArtifact,image:{path:'D:\\Demo\\image.bin',base:0x0800c000,bytes:475136,sha256:'2'.repeat(64)},original_backup:'D:\\Demo\\.mklink\\wireless\\target-original.bin',backup_verified:true,plan_path:'D:\\Demo\\prepared-plan.json',plan_sha256:'3'.repeat(64)};
      if(request.action==='flash')return {programmed:true,verified:true,bytes:475136,bootloader_preserved:true,options_preserved:true,external_flash_programmed:false};
      if(request.action==='verify_flash')return {programmed:false,readback_only:true,verified:true,reset_once:true,bytes:475136,bootloader_preserved:true,options_preserved:true,external_flash_programmed:false};
      const channel=String((p.channels as number[])[0]);const text=`演示 RTT CH${channel} · 未操作硬件\nMW-HIL:20:a56c3917\n${p.input_text?'MW-ECHO:'+p.input_text+'\n':''}`;const hex=Array.from(new TextEncoder().encode(text),n=>n.toString(16).padStart(2,'0')).join('');return {seconds:p.duration,channels:{[channel]:hex},stats:{event_gaps:0}};
    };
    setTimeout(()=>{if(targetJob.id!==id||!targetJob.running)return;targetJob={...targetJob,running:false,phase:'complete',result:result()};},500);
  },

};
