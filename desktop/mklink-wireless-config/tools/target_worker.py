"""One bounded native-target action, brokered through the desktop's connection.

stdin/stdout carry correlated JSON frames only. Credentials never enter command
arguments or diagnostics. The desktop retains its existing USB/LAN/BLE handle.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import uuid
from mklink_wireless import WirelessLink,native_device,NATIVE_SDK_VERSION
from target_ops import (FLASH,APP,END,RAM,RAM_END,identity,read_memory,write_ram,
                        internal_segments,prepare_internal_image,verify_image,
                        flash_application,verify_programmed_application,benchmark_memory,capture_rtt,checked_range)
from advanced_ops import capture_watch,capture_trace
from native_bulk import read_flash_binary,performance_sweep


class Broker:
    def __init__(self,source,sink):
        self.source=source;self.sink=sink;self.lock=threading.RLock();self.frame_lock=threading.Lock();self.sequence=0;self.stop=threading.Event();self.action=''
    def emit(self,frame):
        wire=json.dumps(frame,ensure_ascii=False,separators=(',',':'))+'\n'
        with self.frame_lock:self.sink.write(wire);self.sink.flush()
    def rpc(self,method,params):
        with self.lock:
            self.sequence+=1;ident=self.sequence
            self.emit(dict(kind='rpc',id=ident,method=method,params=params))
            line=self.source.readline(65537)
            if not line or len(line)>65536:raise ConnectionError('Desktop RPC broker closed or exceeded frame limit')
            reply=json.loads(line)
            if reply.get('id')!=ident:raise ConnectionError('Desktop broker reply identity mismatch')
            if reply.get('stop_requested'):self.stop.set()
            if not reply.get('ok'):raise ConnectionError(str(reply.get('error','Desktop transport failure')))
            return reply['data']
    def progress(self,phase,done,total):
        if self.action=='prepare_flash' and self.stop.is_set():raise RuntimeError('烧录准备已停止，目标尚未烧录')
        self.emit(dict(kind='progress',phase=phase,done=done,total=total))


def inspect_artifact(path):
    path=Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size>16*1024*1024:raise ValueError('Firmware must be a regular file no larger than16MiB')
    suffix=path.suffix.lower()
    rtt_address=None
    if suffix in ('.axf','.elf'):
        segments,excluded=internal_segments(path)
        if segments[0][0]!=APP:raise ValueError('APP vector segment must start at0x0800C000')
        total=sum(len(b) for _,b in segments)
        from elftools.elf.elffile import ELFFile
        with path.open('rb') as source:
            symbols=ELFFile(source).get_section_by_name('.symtab')
            if symbols:
                matches=[int(s['st_value']) for s in symbols.iter_symbols() if s.name=='_SEGGER_RTT']
                if len(matches)==1 and RAM<=matches[0]<RAM_END and matches[0]%4==0:rtt_address=matches[0]
    elif suffix=='.bin':
        total=path.stat().st_size;excluded=[]
        if not 8<=total<=END-APP:raise ValueError('BIN must contain an internal APP image at0x0800C000')
    else:raise ValueError('Select an AXF/ELF or internal APP BIN; combined HEX/external flash programming is not exposed')
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),internal_bytes=total,
                base=APP,end=END,excluded_external_segments=excluded,rtt_address=rtt_address)


def number(value):
    if type(value) is int:return value
    if type(value) is str:return int(value,0)
    raise ValueError('Integer or0x-prefixed address required')


def perform(request,broker):
    action=request.get('action');params=request.get('params') or {}
    if action=='inspect':return inspect_artifact(params['artifact'])
    if action not in ['identify','read','write','prepare_flash','flash','verify_flash','benchmark','rtt','superwatch','rtos_trace','binary_read','performance']:raise ValueError('Unsupported target action')
    root=Path(request['project_root']).resolve(strict=True)
    if not root.is_dir():raise ValueError('Existing target project directory required')
    if action in ('read','write'):
        address=number(params['address']);data=None
        if action=='write':
            text=params['data_hex']
            if type(text) is not str or len(text)>8192:raise ValueError('RAM hex input exceeds4096bytes')
            data=bytes.fromhex(text);size=len(data)
        else:size=number(params['size'])
        checked_range(address,size,write=action=='write')
    artifact=inspect_artifact(params['artifact']) if action=='prepare_flash' else None
    if artifact and artifact['sha256']!=params.get('source_sha256'):raise ValueError('Firmware changed since preview; inspect again')
    plan=None
    if action in ('flash','verify_flash'):
        plan_path=Path(params['plan_path']).resolve(strict=True);raw=plan_path.read_bytes()
        if not params.get('confirm') or hashlib.sha256(raw).hexdigest()!=params.get('plan_sha256'):
            raise ValueError('Explicit confirmation of the exact prepared plan required')
        plan=json.loads(raw)
        if plan['state']!='PREPARED' or plan['node_id']!=request['node_id']:raise ValueError('Prepared plan identity mismatch')
        if hashlib.sha256(Path(plan['original_backup']).read_bytes()).hexdigest()!=plan['original_sha256']:
            raise ValueError('Original target backup changed; no flash')
    link=WirelessLink(broker.rpc,request['node_id'])
    broker.performance=link.performance
    with native_device(link,project_root=root,axf=request.get('axf') or None,multiplex=action not in ('prepare_flash','flash','verify_flash','read','benchmark','binary_read','performance')) as device:
        target=identity(device)
        expected=params.get('expected_uid')
        if action in ('write','prepare_flash','flash','verify_flash','benchmark','rtt','superwatch','rtos_trace','binary_read','performance') and (not expected or target['uid']!=expected):
            raise ValueError('Identify and confirm this target UID before a write workflow')
        if action=='identify':return target
        if action=='benchmark':return dict(target=target,**benchmark_memory(device,link,number(params.get('repetitions',5))))
        if action=='performance':return dict(target=target,**performance_sweep(device,link,repetitions=number(params.get('repetitions',3)),expected_sha256=params.get('expected_sha256'),progress=broker.progress))
        if action=='binary_read':
            data,report=read_flash_binary(device,number(params['address']),number(params['size']),progress=lambda done,total:broker.progress('binary_read',done,total))
            if params.get('expected_sha256') and hashlib.sha256(data).hexdigest()!=params['expected_sha256']:raise RuntimeError('Binary dump differs from confirmed reference')
            folder=root/'.mklink/wireless/captures';folder.mkdir(parents=True,exist_ok=True);output=folder/(uuid.uuid4().hex+'-flash.bin');output.write_bytes(data)
            return dict(target=target,**report,path=str(output))
        if action=='superwatch':return dict(target=target,**capture_watch(device,number(params['address']),number(params['size']),float(params.get('duration',10)),float(params.get('period',.05)),root=root,rtt_address=number(params['rtt_address']) if params.get('rtt_address') is not None else None,stop=broker.stop,progress=broker.progress))
        if action=='rtos_trace':return dict(target=target,**capture_trace(device,number(params['address']),float(params.get('duration',10)),root=root,stop=broker.stop,progress=broker.progress))
        if action=='read':
            started=time.monotonic();data=read_memory(device,address,size)
            return dict(target=target,address=address,bytes=size,data_hex=data.hex(),read_ms=round((time.monotonic()-started)*1000,3))
        if action=='write':return dict(target=target,**write_ram(device,address,data))
        if action=='prepare_flash':
            work=root/'.mklink'/'wireless'/uuid.uuid4().hex;work.mkdir(parents=True,exist_ok=False)
            backup=work/'target-original.bin';digest=hashlib.sha256()
            with backup.open('xb') as output:
                if device._wireless_binary_bulk:
                    data=read_flash_binary(device,FLASH,END-FLASH,progress=lambda done,total:broker.progress('backup',done,total))[0]
                    output.write(data);digest.update(data)
                else:
                    for offset in range(0,END-FLASH,4096):
                        chunk=read_memory(device,FLASH+offset,4096);output.write(chunk);digest.update(chunk)
                        broker.progress('backup',offset+4096,END-FLASH)
            verify_image(device,backup,FLASH,broker.progress)
            if hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest()!=artifact['sha256']:
                raise ValueError('Firmware changed while preparing; inspect again, target not programmed')
            image=work/'application-preserved.bin'
            if Path(artifact['path']).suffix.lower() in ('.axf','.elf'):
                image_info=prepare_internal_image(artifact['path'],backup,image)
            else:
                original=backup.read_bytes();payload=bytearray(original[APP-FLASH:]);source=Path(artifact['path']).read_bytes();payload[:len(source)]=source
                stack=int.from_bytes(payload[:4],'little');entry=int.from_bytes(payload[4:8],'little')
                if not RAM<=stack<=RAM_END or not APP<=(entry&~1)<END or not entry&1:raise ValueError('Invalid APP vectors')
                image.write_bytes(payload);image_info=dict(path=str(image),base=APP,bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest(),excluded_external_segments=[])
            plan=dict(state='PREPARED',node_id=request['node_id'],target=target,source=artifact,image=image_info,
                      original_backup=str(backup),original_sha256=digest.hexdigest(),backup_verified=True,workdir=str(work),created_at=time.time())
            manifest=work/'prepared-plan.json';manifest.write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
            return dict(**plan,plan_path=str(manifest),plan_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
        if action=='verify_flash':
            return verify_programmed_application(device,plan['image']['path'],plan['image']['sha256'],
                                                 plan['original_backup'],plan['target'],progress=broker.progress)
        if action=='flash':
            if target!=plan['target']:raise ValueError('Target identity/options changed since preparation')
            broker.progress('preflight_verify',0,END-FLASH)
            verify_image(device,plan['original_backup'],FLASH,broker.progress)
            return flash_application(device,link,plan['image']['path'],plan['image']['sha256'],plan['workdir'],
                                     expected_uid=expected,progress=broker.progress)
        if action=='rtt':
            def output(channel,data):broker.emit(dict(kind='rtt',channel=channel,data_hex=data.hex()))
            return capture_rtt(device,number(params['address']),params.get('channels',[0]),float(params.get('duration',10)),
                               input_text=params.get('input_text',''),input_channel=params.get('input_channel'),progress=output,stop=broker.stop)


def main():
    sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    source=sys.stdin;sink=sys.stdout;broker=Broker(source,sink)
    if sys.argv[1:]==['--self-test']:
        from mklink.cmsis_dap.algorithm_catalog import extract_algorithm
        from target_ops import native_f411_algorithm
        algorithm=native_f411_algorithm();payload=extract_algorithm(algorithm)
        broker.emit(dict(kind='self_test',sdk=NATIVE_SDK_VERSION,algorithm_count=1,algorithm_source=algorithm.source_kind,flm_bytes=len(payload),flm_sha256=hashlib.sha256(payload).hexdigest(),
                         algorithm=algorithm.algorithm_id,hardware_opened=False))
        return 0
    first=source.readline(65537)
    try:
        if len(first)>65536:raise ValueError('Initial action frame too large')
        request=json.loads(first)
        broker.action=request.get('action','')
        # Native SDK progress is diagnostic text, never mixed into RPC frames.
        sys.stdout=sys.stderr
        result=perform(request,broker)
        if isinstance(result,dict) and hasattr(broker,'performance'):result['wireless_performance']=broker.performance()
        broker.emit(dict(kind='result',ok=True,data=result));return 0
    except Exception as error:
        detail=[str(error),*getattr(error,'__notes__',[])];cause=error.__cause__
        for _ in range(3):
            if cause is None:break
            detail.append(type(cause).__name__+': '+str(cause));cause=cause.__cause__
        broker.emit(dict(kind='result',ok=False,error=' | '.join(detail)[:4000]))
        return 1


if __name__=='__main__':raise SystemExit(main())
