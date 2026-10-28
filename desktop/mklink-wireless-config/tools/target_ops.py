"""STM32F411 application operations using the unchanged native MKLink SDK.

Writes are bounded to SRAM or internal APP sectors3..7. Bootloader sectors,
external Flash, option bytes, protection and supply controls are not exposed.
"""
from pathlib import Path
import hashlib
import json
import struct
import time

FLASH=0x08000000
APP=0x0800c000
END=0x08080000
RAM=0x20000000
RAM_END=0x20020000


def checked_range(address,size,*,write=False):
    if type(address) is not int or type(size) is not int or not 1<=size<=4096:
        raise ValueError('Integer address and size1..4096 required')
    ranges=[(RAM,RAM_END)] if write else [(FLASH,END),(RAM,RAM_END)]
    if not any(start<=address and address+size<=end for start,end in ranges):
        raise ValueError('Range outside STM32F411 SRAM/internal Flash')


def identity(device):
    debug=int.from_bytes(device.read_memory(0xe0042000,4),'little')
    kib=int.from_bytes(device.read_memory(0x1fff7a22,2),'little')
    uid=device.read_memory(0x1fff7a10,12).hex()
    options=int.from_bytes(device.read_memory(0x40023c14,4),'little')
    if debug&0xfff!=0x431 or kib!=512 or (options>>8)&255!=0xaa:
        raise RuntimeError('Expected readable STM32F411xE with512KiB; no protection recovery attempted')
    return dict(part='STM32F411CEUx',uid=uid,debug_id=hex(debug),flash_bytes=kib*1024,option_control=hex(options))


def read_memory(device,address,size):
    checked_range(address,size)
    if getattr(device,'_wireless_binary_bulk',False) is True and size>=4096 and FLASH<=address and address+size<=END:
        from native_bulk import read_flash_binary
        return read_flash_binary(device,address,size)[0]
    maximum=4096
    if getattr(device,'_wireless_text_reads',False) is True:
        selected=getattr(device,'_wireless_bulk_size',1024)
        maximum=selected if type(selected) is int and selected in (1024,4096) else 1024
    chunks=[]
    for offset in range(0,size,maximum):
        count=min(maximum,size-offset);chunk=device.read_memory(address+offset,count)
        if len(chunk)!=count:raise RuntimeError('Incomplete native read; not replayed')
        chunks.append(chunk)
    data=b''.join(chunks)
    if len(data)!=size:raise RuntimeError('Incomplete memory read; not replayed')
    return data


def read_flash_range(device,address,size,progress=None):
    if type(address) is not int or type(size) is not int or size<1 or not FLASH<=address or address+size>END:
        raise ValueError('Internal Flash snapshot range required')
    if getattr(device,'_wireless_binary_bulk',False) is True and size>=4096:
        from native_bulk import read_flash_binary
        return read_flash_binary(device,address,size,progress=progress)[0]
    return b''.join(read_memory(device,address+offset,min(4096,size-offset)) for offset in range(0,size,4096))


def write_ram(device,address,data):
    if not isinstance(data,bytes):raise TypeError('RAM data must be bytes')
    checked_range(address,len(data),write=True)
    device.write_memory(address,data)
    actual=device.read_memory(address,len(data))
    if actual!=data:raise RuntimeError('RAM readback mismatch; write not repeated')
    return dict(address=address,bytes=len(data),verified=True)


def internal_segments(path):
    from elftools.elf.elffile import ELFFile
    path=Path(path);segments=[];excluded=[]
    with path.open('rb') as source:
        elf=ELFFile(source)
        for segment in elf.iter_segments():
            if segment['p_type']!='PT_LOAD' or not segment['p_filesz']:continue
            address=int(segment['p_paddr']);data=segment.data()
            if APP<=address and address+len(data)<=END:segments.append((address,data))
            elif address>=0x90000000:excluded.append(dict(address=address,bytes=len(data)))
            else:raise ValueError('Image includes bootloader, system or out-of-range load segment')
    if not segments:raise ValueError('No internal STM32F411 APP load segment')
    segments.sort()
    for i,(address,data) in enumerate(segments):
        if i and segments[i-1][0]+len(segments[i-1][1])>address:raise ValueError('Overlapping image load segments')
    return segments,excluded


def prepare_internal_image(axf,backup,destination):
    """Preserve bytes outside load segments, including the last erase sector."""
    original=Path(backup).read_bytes()
    if len(original)!=524288:raise ValueError('Complete512KiB target backup required')
    segments,excluded=internal_segments(axf)
    image=bytearray(original[APP-FLASH:])
    for address,data in segments:image[address-APP:address-APP+len(data)]=data
    stack,entry=struct.unpack_from('<II',image)
    if not RAM<=stack<=RAM_END or not APP<=(entry&~1)<END or not entry&1:
        raise ValueError('Invalid APP Cortex-M vector table')
    dest=Path(destination)
    if dest.exists():raise ValueError('Preserve existing image evidence')
    dest.write_bytes(image)
    return dict(path=str(dest.resolve()),base=APP,bytes=len(image),sha256=hashlib.sha256(image).hexdigest(),
                axf_sha256=hashlib.sha256(Path(axf).read_bytes()).hexdigest(),excluded_external_segments=excluded,
                preserved_bootloader_bytes=APP-FLASH,preserved_uncovered_app_bytes=True)


def verify_image(device,path,base,progress=None):
    expected=Path(path).read_bytes()
    if not FLASH<=base or base+len(expected)>END:raise ValueError('Internal Flash verification range required')
    digest=hashlib.sha256()
    if getattr(device,'_wireless_binary_bulk',False) is True and len(expected)>=4096:
        actual=read_flash_range(device,base,len(expected),progress=(lambda done,total:progress('verify',done,total)) if progress else None)
        if actual!=expected:raise RuntimeError('Native binary Flash mismatch; no replay')
        return dict(verified=True,bytes=len(expected),sha256=hashlib.sha256(actual).hexdigest())
    for offset in range(0,len(expected),4096):
        chunk=expected[offset:offset+4096];actual=read_memory(device,base+offset,len(chunk))
        if actual!=chunk:raise RuntimeError(f'Flash mismatch at0x{base+offset:08x}; no replay')
        digest.update(actual)
        if progress:progress('verify',offset+len(chunk),len(expected))
    return dict(verified=True,bytes=len(expected),sha256=digest.hexdigest())


def native_f411_algorithm():
    """Use the SDK's integrity-checked embedded FLM catalog, independent of local Packs."""
    from mklink.cmsis_dap.builtin_flm_bundle import discover_builtin_flm_algorithms
    from mklink.cmsis_dap.algorithm_catalog import resolve_firmware_algorithms
    selection=resolve_firmware_algorithms(discover_builtin_flm_algorithms('STM32F411CEUx'),((APP,END),))
    if len(selection)!=1:raise RuntimeError('One exact built-in internal Flash algorithm required')
    algorithm=selection[0].algorithm
    if algorithm.flash_start!=FLASH or algorithm.flash_size!=524288 or algorithm.ram_start!=RAM:
        raise RuntimeError('Algorithm geometry does not match verified target')
    return algorithm


def flash_application(device,link,path,expected_sha256,workdir,*,expected_uid,progress=None):
    """Native FLM and load.bin; only file delivery changes to S3 MSC."""
    from mklink.cmsis_dap.algorithm_catalog import extract_algorithm
    p=Path(path);image=p.read_bytes()
    if len(image)!=END-APP or hashlib.sha256(image).hexdigest()!=expected_sha256:
        raise ValueError('Exact sector-preserving APP image and acknowledged hash required')
    before=identity(device)
    if before['uid']!=expected_uid:raise RuntimeError('Target identity changed; no flash performed')
    boot=read_flash_range(device,FLASH,APP-FLASH)
    if len(boot)!=APP-FLASH:raise RuntimeError('Incomplete Bootloader preservation read')
    algorithm=native_f411_algorithm()
    flm=extract_algorithm(algorithm,Path(workdir)/'algorithms')
    device._bridge._leave_multiplex()
    def file_progress(phase):
        return (lambda event,done,total:progress(phase+'_verify' if event=='verify' else phase,done,total)) if progress else None
    remote_flm=link.upload_file(flm,'FLM',progress=file_progress('algorithm_upload'),expected_sha256=hashlib.sha256(Path(flm).read_bytes()).hexdigest())
    remote_bin=link.upload_file(p,'BIN',progress=file_progress('image_upload'),expected_sha256=expected_sha256)
    # Finish both verified file transfers before the probe prepares the target.
    # A slow radio or failed file commit must not strand a loaded algorithm.
    if hashlib.sha256(p.read_bytes()).hexdigest()!=expected_sha256:raise RuntimeError('Local image changed before algorithm load; no program command sent')
    if not device._flash.load_flm(remote_flm,hex(FLASH),hex(RAM)):
        raise RuntimeError('Native FLM load rejected; target program not attempted')
    native_copy=device._flash._copy_to_microkeen
    def staged_copy(local_path,name=None):
        if Path(local_path).resolve()!=p.resolve() or hashlib.sha256(Path(local_path).read_bytes()).hexdigest()!=expected_sha256:
            raise RuntimeError('Prepared local image changed; no program command sent')
        return remote_bin
    device._flash._copy_to_microkeen=staged_copy
    try:
        if progress:progress('program',0,len(image))
        result=device._flash.burn_bin(str(p),hex(APP))
    finally:device._flash._copy_to_microkeen=native_copy
    if not result.get('success'):raise RuntimeError('Native load.bin did not report programming success; not retried')
    text_reads=getattr(device,'_wireless_text_reads',False) is True
    if not text_reads and device._bridge.enable_multiplex() is None:raise RuntimeError('Native verification transport unavailable')
    verified=verify_image(device,p,APP,progress)
    after=identity(device)
    if after!=before or read_flash_range(device,FLASH,APP-FLASH)!=boot:
        raise RuntimeError('Target identity, options or Bootloader preservation mismatch')
    mux=device._bridge._mux
    if mux is not None and not mux.supports_software_reset:
        # Choose the advertised native reset path before any reset attempt.
        # This is not recovery/replay after a failed or uncertain reset.
        device._bridge._leave_multiplex()
    device.reset()  # One explicit native reset after complete verified programming.
    return dict(programmed=True,**verified,uid=after['uid'],algorithm_id=algorithm.algorithm_id,
                native_program_ms=result.get('time_ms'),native_program_timing_scope='SDK load.bin wall time includes reply transport and native500ms settle, excludes verified file staging/readback',
                algorithm_source=algorithm.source_kind,bootloader_preserved=True,options_preserved=True,
                external_flash_programmed=False,reset_once=True,readback_mode='native_binary_B1' if getattr(device,'_wireless_binary_bulk',False) is True else (('native_pika_'+str(getattr(device,'_wireless_bulk_size',1024))) if text_reads else 'native_mux'))


def verify_programmed_application(device,path,expected_sha256,original_backup,expected_target,*,progress=None):
    """Explicit recovery: verify an existing image, never load/burn it again."""
    image=Path(path).read_bytes();original=Path(original_backup).read_bytes()
    if len(image)!=END-APP or hashlib.sha256(image).hexdigest()!=expected_sha256 or len(original)!=END-FLASH:
        raise ValueError('Exact acknowledged APP and original full backup required')
    before=identity(device)
    if before!=expected_target:raise RuntimeError('Target identity/options changed; no recovery reset')
    verified=verify_image(device,path,APP,progress)
    if read_flash_range(device,FLASH,APP-FLASH)!=original[:APP-FLASH] or identity(device)!=before:
        raise RuntimeError('Bootloader/identity preservation mismatch; no recovery reset')
    mux=device._bridge._mux
    if mux is not None and not mux.supports_software_reset:device._bridge._leave_multiplex()
    device.reset()
    return dict(**verified,uid=before['uid'],readback_only=True,programmed=False,reset_once=True,
                bootloader_preserved=True,options_preserved=True,external_flash_programmed=False)


def benchmark_memory(device,link,repetitions=5):
    """Controlled1KiB/4KiB window comparison, same stable Flash, no writes."""
    import math
    if type(repetitions) is not int or not 2<=repetitions<=10:raise ValueError('Benchmark repetitions2..10 required')
    maximum=link.read_max;original_bulk=getattr(device,'_wireless_bulk_size',1024);expected=None;cases=[]
    try:
        for window in sorted(set([min(1024,maximum),maximum])):
            with link.lock:link.read_max=window
            device._wireless_bulk_size=4096 if window>=4096 else 1024
            timings=[]
            for _ in range(repetitions):
                start=time.monotonic();data=read_memory(device,APP,4096);elapsed=time.monotonic()-start
                digest=hashlib.sha256(data).hexdigest()
                if expected is None:expected=digest
                if digest!=expected:raise RuntimeError('Benchmark Flash bytes changed; no replay')
                timings.append(round(elapsed*1000,3))
            ordered=sorted(timings)
            cases.append(dict(window_bytes=window,native_command_bytes=device._wireless_bulk_size,samples_ms=timings,
                              p50_ms=ordered[math.ceil(len(ordered)*.5)-1],p95_ms=ordered[math.ceil(len(ordered)*.95)-1],
                              payload_bytes=4096*repetitions,goodput_bytes_s=round(4096*repetitions/(sum(timings)/1000),2)))
    finally:
        with link.lock:link.read_max=maximum
        device._wireless_bulk_size=original_bulk
    return dict(readonly=True,address=APP,read_bytes=4096,repetitions=repetitions,data_sha256=expected,cases=cases,
                swd_clock_requested_hz=1000000,scope='Steady native Flash read only; excludes discovery, worker startup and identity checks')


def capture_rtt(device,address,channels,duration,*,input_text='',input_channel=None,progress=None,stop=None):
    if type(duration) not in (float,int) or not .1<=duration<=30:raise ValueError('RTT duration must be0.1..30seconds')
    if type(address) is not int or address%4 or not RAM<=address<RAM_END:raise ValueError('Aligned known writable RAM RTT address required')
    if not channels or len(set(channels))!=len(channels) or any(type(c) is not int or not 0<=c<=7 for c in channels):
        raise ValueError('Unique actual RTT channels0..7 required')
    data=input_text.encode('utf-8')
    if len(data)>256:raise ValueError('RTT downlink exceeds256bytes; not split')
    info=device.rtt_start(addr=hex(address),channel=channels[0],channels=channels)
    output={c:bytearray() for c in channels};started=time.monotonic()
    try:
        if data:device.rtt_write(data,channel=input_channel if input_channel is not None else channels[0])
        while time.monotonic()-started<duration and not (stop and stop.is_set()):
            for channel,chunk in device.rtt_read_channels(.1).items():
                output[channel].extend(chunk)
                if sum(len(data) for data in output.values())>65536:raise RuntimeError('Bounded RTT capture full; stopped without silent truncation')
                if chunk and progress:progress(channel,bytes(chunk))
        stats=device._bridge._mux.stats()
    finally:device.rtt_stop()
    return dict(seconds=round(time.monotonic()-started,3),transport=info,
                channels={str(c):bytes(b).hex() for c,b in output.items()},stats=stats)
