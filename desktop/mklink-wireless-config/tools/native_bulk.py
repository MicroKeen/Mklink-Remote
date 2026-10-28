"""Finite CRC-checked native MKLink B1 dumps. No new SWD implementation,
no polling substitute, no fallback/replay after an uncertain native result.
"""
import hashlib,time,sys
FLASH=0x08000000
END=0x08080000
USB_FS_BULK_CEILING=1216000

def finite_parser(region_sizes,command):
    from mklink.dump_memory import DumpMemoryParser,MAGIC
    class ExactPreludeParser(DumpMemoryParser):
        def __init__(self):
            super().__init__(region_sizes=region_sizes)
            self.pending=bytearray();self.prelude_complete=False;self.command_echo_bytes=0
        def feed(self,data):
            if self.prelude_complete:return super().feed(data)
            self.pending.extend(data);at=self.pending.find(MAGIC)
            if at<0:
                if len(self.pending)>len(command)+64:raise RuntimeError('Unexpected native dump prelude; no bytes silently discarded')
                return []
            prelude=bytes(self.pending[:at])
            # Exact V4.7.2 REPL echo observed on the physical probe. Arbitrary
            # junk, gaps between frames and CRC errors remain fatal.
            if prelude not in (b'',command+b'\n\r\n>>> '):
                raise RuntimeError('Unrecognized native dump command echo; capture rejected')
            self.command_echo_bytes=len(prelude);self.prelude_complete=True
            wire=bytes(self.pending[at:]);self.pending.clear()
            return super().feed(wire)
    return ExactPreludeParser()

def read_flash_binary(device,address,size,progress=None):
    if type(address) is not int or type(size) is not int or address%4 or not 4096<=size<=524288 or not FLASH<=address<address+size<=END:
        raise ValueError('Native binary Flash read requires aligned4KiB..512KiB within STM32F411')
    from mklink.dump_memory import DumpMemoryStreamSession,DumpSampleAssembler,build_dump_mem_command
    bridge=device._bridge;link=bridge.link
    bridge._leave_multiplex() # Normal acknowledged native mode transition.
    bridge.supports_multiplex() # Resolve native capabilities before USB timing.
    measured=getattr(link,'usb_metrics_supported',False) is True
    if measured:
        begin=link.call('probe.metrics.reset')
        if begin['rx_pending']:raise RuntimeError('USB contains an undrained previous stream; no new dump sent')
    session=DumpMemoryStreamSession(bridge,[(address,size)],0.0,allow_legacy_bulk=True)
    session.parser=finite_parser([size],build_dump_mem_command([(address,size)],0.0).encode())
    assembler=DumpSampleAssembler([size],ordered=True)
    result=None;metrics={};started=time.perf_counter();deadline=started+180;last_progress=started
    try:
        session.start()
        if session._mux_watch is not None:raise RuntimeError('Finite B1 dump expected; continuous sampler not accepted')
        while time.perf_counter()<deadline:
            frames=session.read_frames(max_bytes=1048576)
            if frames:last_progress=time.perf_counter()
            if session.parser.crc_errors:raise RuntimeError('Native dump frame CRC failed; no replay')
            for frame in frames:
                payloads=assembler.feed(frame)
                if progress and frame.get('format')=='B1':progress(min(size,(frame['block_index']+1)*frame['block_size']),size)
                if payloads is not None:
                    if len(payloads)!=1 or len(payloads[0])!=size:raise RuntimeError('Incomplete native B1 region')
                    result=bytes(payloads[0]);break
            if result is not None:break
            if time.perf_counter()-last_progress>30:raise TimeoutError('No native dump progress for30seconds; no replay')
            if not frames:time.sleep(.001)
        if result is None:raise TimeoutError('Finite native dump exceeded180seconds; no replay')
        read_seconds=time.perf_counter()-started
        # Snapshot BEFORE stop/identity commands; USB timestamps therefore end
        # at the finite dump producer, independently of the radio drain time.
        if measured:metrics=link.call('probe.metrics.snapshot')
    finally:
        primary=sys.exc_info()[1]
        try:session.stop()
        except Exception as stop_error:
            if primary is None:raise
            primary.add_note('Native stop also failed; session is not reusable: '+str(stop_error))
    stats=session.stats
    if any(stats.get(k,0) for k in ('parser_crc_errors','parser_dropped_frames','parser_dropped_bytes','firmware_flagged_frames','firmware_read_errors')):
        raise RuntimeError('Native B1 integrity failure: '+str(stats))
    elapsed=time.perf_counter()-started
    usb_span=(metrics.get('last_rx_us',0)-metrics.get('tx_start_us',0))/1e6 if measured else 0
    report=dict(protocol='native_dump_memory_B1',address=address,bytes=size,sha256=hashlib.sha256(result).hexdigest(),
                read_seconds=round(read_seconds,6),total_seconds=round(elapsed,6),payload_bytes_s=round(size/read_seconds,2),
                including_cleanup_bytes_s=round(size/elapsed,2),read_window_bytes=link.read_max,stats=stats,usb_metrics=metrics,
                recognized_command_echo_bytes=session.parser.command_echo_bytes,
                usb_scope='S3 USB command TX start to final finite-dump RX completion; includes V4 SWD and USB, excludes PC/wireless drain')
    if usb_span>0:
        report.update(usb_producer_seconds=round(usb_span,6),usb_wire_bytes_s=round(metrics['rx_bytes']/usb_span,2),
                      usb_producer_payload_bytes_s=round(size/usb_span,2),usb_fs_theoretical_bulk_bytes_s=USB_FS_BULK_CEILING,
                      usb_fs_wire_utilization_percent=round(metrics['rx_bytes']/usb_span/USB_FS_BULK_CEILING*100,3))
    device._wireless_last_bulk_report=report
    return result,report

def performance_sweep(device,link,*,repetitions=3,expected_sha256=None,progress=None):
    if type(repetitions) is not int or not 1<=repetitions<=5:raise ValueError('Performance repetitions1..5 required')
    from mklink.debug_speed import ClockProfileUnavailable,apply_bridge_profile,PROFILES
    results=[];failures=[];best_clock=1000000;best_goodput=0
    try:
        device._flash.set_swd_clock(1000000)
        baseline,baseline_report=read_flash_binary(device,FLASH,524288)
        digest=hashlib.sha256(baseline).hexdigest()
        if expected_sha256 and digest!=expected_sha256:raise RuntimeError('Current target differs from the qualified reference; no writes performed')
        for clock in [1000000,4000000,10000000,20000000,30000000]:
            try:
                if clock==1000000:device._flash.set_swd_clock(clock)
                else:apply_bridge_profile(device._bridge,next(p for p,hz in PROFILES.items() if hz==clock))
            except ClockProfileUnavailable as error:
                failures.append(dict(clock_hz=clock,setting_rejected=True,error=str(error)));break
            case=[]
            for index in range(repetitions):
                data,report=read_flash_binary(device,FLASH,65536)
                if data!=baseline[:65536]:raise RuntimeError('Target Flash changed or clock read corrupted; no replay')
                case.append(report)
                if progress:progress('performance_clock',index+1,repetitions)
            rate=sum(row['bytes'] for row in case)/sum(row['read_seconds'] for row in case)
            producer=sum(row['bytes'] for row in case)/sum(row['usb_producer_seconds'] for row in case) if all(row.get('usb_producer_seconds') for row in case) else rate
            results.append(dict(clock_requested_and_acknowledged_hz=clock,samples=case,goodput_bytes_s=round(rate,2),usb_producer_payload_bytes_s=round(producer,2)))
            if producer>best_goodput:best_clock=clock;best_goodput=producer
        device._flash.set_swd_clock(best_clock)
        windows=[]
        for size in [4096,32768,131072,524288]:
            case=[]
            for index in range(repetitions):
                data,report=read_flash_binary(device,FLASH,size)
                if data!=baseline[:size]:raise RuntimeError('Binary block comparison failed; no replay')
                case.append(report)
                if progress:progress('performance_block',index+1,repetitions)
            windows.append(dict(block_bytes=size,samples=case,goodput_bytes_s=round(sum(x['bytes'] for x in case)/sum(x['read_seconds'] for x in case),2)))
        return dict(readonly=True,baseline_sha256=digest,baseline=baseline_report,repetitions=repetitions,
                    clocks=results,blocks=windows,clock_rejections=failures,best_tested_clock_hz=best_clock,
                    best_tested_payload_bytes_s=max(x['goodput_bytes_s'] for x in windows),
                    best_tested_usb_producer_payload_bytes_s=round(max([best_goodput]+[x['usb_producer_payload_bytes_s'] for row in windows for x in row['samples'] if x.get('usb_producer_payload_bytes_s')]),2),
                    note='Highest stable result in this finite tested matrix; clock acknowledgement is not an oscilloscope measurement',
                    default_swd_clock_restored_hz=1000000)
    finally:
        if not link.poisoned:device._flash.set_swd_clock(1000000)
