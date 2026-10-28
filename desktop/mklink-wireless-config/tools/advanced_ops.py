"""Bounded native SuperWatch and FreeRTOS SystemView captures, no host polling
substitute and no RT-Thread TCB interpretation on the FreeRTOS target.
"""
import hashlib,json,math,statistics,time,uuid,struct
from contextlib import contextmanager
from pathlib import Path
from target_ops import RAM,RAM_END

@contextmanager
def retained_rtt_tail(device,address):
    """Keep the SDK's deliberately cleared startup queue during Trace handoff.

    Native MUX parses and validates every frame as usual. Only this owned
    session's initial channel1 queue is retained for its first normal read.
    """
    transport=device._bridge.enable_multiplex()
    if transport is None:raise RuntimeError('Native MUX RTT required for final Trace tail')
    original=transport.drain;starting=True;queued=[];started=False
    def retain(frame_type,channel=None):
        frames=original(frame_type,channel)
        if frame_type==0x40 and channel==1:
            if starting:queued.extend(frames);return []
            if queued:frames=queued[:]+frames;queued.clear()
        return frames
    transport.drain=retain
    try:
        device.rtt_start(addr=hex(address),channel=1,channels=[1],mode=1)
        started=True;starting=False
        yield
    finally:
        try:
            if started:device.rtt_stop()
        finally:transport.drain=original

def bounds(address,size,duration):
    if type(address) is not int or address%4 or type(size) is not int or not 4<=size<=256 or not RAM<=address<address+size<=RAM_END:
        raise ValueError('Aligned SRAM capture region4..256bytes required')
    if type(duration) not in (int,float) or not math.isfinite(duration) or not .1<=duration<=30:
        raise ValueError('Capture duration0.1..30seconds required')

def capture_watch(device,address,size,duration,period,*,root,rtt_address=None,stop=None,progress=None):
    bounds(address,size,duration)
    if type(period) not in (int,float) or not math.isfinite(period) or not .01<=period<=1:
        raise ValueError('SuperWatch period10..1000ms required; unbounded full speed is not exposed')
    if rtt_address is not None:bounds(rtt_address,4,duration)
    from mklink.dump_memory import DumpMemoryStreamSession
    if device._bridge.supports_multiplex() is not True:raise RuntimeError('Native MUX SuperWatch required; no memory polling fallback')
    folder=Path(root)/'.mklink/wireless/captures';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(uuid.uuid4().hex+'-superwatch.jsonl')
    session=DumpMemoryStreamSession(device._bridge,[(address,size)],period)
    sample_count=0;wire_bytes=0;timestamps=[];values=set();preview=[];rtt_bytes=bytearray();rtt_started=False
    setup_started=time.monotonic();started=setup_started;written=0;active_seconds=0;drain_ms=0
    try:
        if rtt_address is not None:device.rtt_start(addr=hex(rtt_address),channel=2,channels=[2]);rtt_started=True
        session.start()
        if session._mux_watch is None:raise RuntimeError('Native MUX SuperWatch unavailable; legacy stream not accepted')
        started=time.monotonic()
        with path.open('x',encoding='utf-8') as sink:
            def consume(frames):
                nonlocal written,sample_count,wire_bytes
                for frame in frames:
                    regions=[dict(index=i,data_hex=bytes(data).hex()) for i,data in frame['regions']]
                    row=dict(timestamp_us=frame['timestamp_us'],flags=frame.get('flags',0),regions=regions)
                    line=json.dumps(row,separators=(',',':'))+'\n';written+=len(line.encode())
                    if written>16*1024*1024:raise RuntimeError('SuperWatch capture reached16MiB; stopped without silent truncation')
                    sink.write(line);sample_count+=1;timestamps.append(frame['timestamp_us'])
                    for _,data in frame['regions']:wire_bytes+=len(data);values.add(bytes(data))
                    if len(preview)<16:preview.append(row)
            while time.monotonic()-started<duration and not(stop and stop.is_set()):
                consume(session.read_frames())
                if rtt_started:
                    for channel,chunk in device.rtt_read_channels(.01).items():
                        if channel==2:rtt_bytes.extend(chunk)
                    if len(rtt_bytes)>65536:raise RuntimeError('Concurrent RTT capture reached64KiB')
                if progress:progress('superwatch',sample_count,max(1,round(duration/period)))
                time.sleep(.005)
            active_seconds=time.monotonic()-started
            tail_started=time.monotonic();session.stop()
            # The stop ACK follows preceding events on the native byte stream.
            # Drain native decoded frames which arrived while awaiting that ACK;
            # do not silently discard the buffered tail from a fast sampler.
            for _ in range(128):
                tail=session._mux_watch.read_frames()
                if not tail:break
                consume(tail)
            else:raise RuntimeError('Native SuperWatch tail exceeded bounded drain budget')
            if rtt_started:
                for channel,chunk in device.rtt_read_channels(.05).items():
                    if channel==2:rtt_bytes.extend(chunk)
                if len(rtt_bytes)>65536:raise RuntimeError('Concurrent RTT capture reached64KiB')
            drain_ms=round((time.monotonic()-tail_started)*1000,3)
        stats=session.stats
    finally:
        try:session.stop()
        finally:
            if rtt_started:device.rtt_stop()
    elapsed=time.monotonic()-started
    deltas=[b-a for a,b in zip(timestamps,timestamps[1:]) if b>a]
    span=(timestamps[-1]-timestamps[0])/1e6 if len(timestamps)>1 else 0
    ordered=sorted(deltas)
    return dict(native_push=True,host_memory_polling=False,address=address,region_bytes=size,requested_hz=1/period,
                seconds=round(elapsed,3),capture_active_seconds=round(active_seconds,3),setup_ms=round((started-setup_started)*1000,3),stop_and_drain_ms=drain_ms,samples=sample_count,distinct_values=len(values),payload_bytes=wire_bytes,
                received_samples_s=round(sample_count/elapsed,2),target_samples_s=round((sample_count-1)/span,2) if span>0 else None,
                median_target_period_us=statistics.median(deltas) if deltas else None,
                p95_target_period_us=ordered[math.ceil(len(ordered)*.95)-1] if ordered else None,
                stats=stats,preview=preview,rtt_ch2_hex=bytes(rtt_bytes).hex(),capture_path=str(path),
                capture_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),clock_scope='Native V4 sample timestamps; PC arrival rate includes wireless drain and stop overhead')

def capture_trace(device,address,duration,*,root,stop=None,progress=None):
    bounds(address,4,duration)
    folder=Path(root)/'.mklink/wireless/captures';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(uuid.uuid4().hex+'-rtos-trace.jsonl')
    setup_started=time.monotonic()
    info=device.systemview_start(addr=hex(address),channel=1,mode=1,search_size=0)
    started=time.monotonic();events=0;data_bytes=0;written=0;last={};preview=[];event_types={};closed=False
    active_seconds=0;drain_seconds=0;first_event_us=None;last_event_us=None
    active_decoder_drops=0;radio_decoder_drops=0;usb_pending_after_drain=None
    recording_start_us=None;recording_stop_us=None;recording_events=0;prefix_events=0;target_tail_bytes=0
    try:
        with path.open('x',encoding='utf-8') as sink:
            def consume(batch):
                nonlocal last,data_bytes,written,events,first_event_us,last_event_us
                nonlocal recording_start_us,recording_stop_us,recording_events,prefix_events
                last=batch;data_bytes+=batch.get('bytes_read',0)
                for event in batch.get('events',[]):
                    line=json.dumps(event,separators=(',',':'))+'\n';written+=len(line.encode())
                    if written>16*1024*1024:raise RuntimeError('RTOS Trace capture reached16MiB; stopped without silent truncation')
                    sink.write(line);events+=1
                    kind=str(event.get('kind','unknown'));event_types[kind]=event_types.get(kind,0)+1
                    if kind=='trace_start':
                        if recording_start_us is not None:raise RuntimeError('Unexpected second recording START; capture epochs must remain separate')
                        recording_start_us=event.get('t_us')
                    if recording_start_us is None:prefix_events+=1
                    elif recording_stop_us is None:
                        recording_events+=1
                        if kind=='trace_stop':recording_stop_us=event.get('t_us')
                    if isinstance(event.get('t_us'),(int,float)):
                        if first_event_us is None:first_event_us=event['t_us']
                        last_event_us=event['t_us']
                    if len(preview)<24:preview.append(event)
            while time.monotonic()-started<duration and not(stop and stop.is_set()):
                consume(device.systemview_read(.1))
                if progress:progress('rtos_trace',round((time.monotonic()-started)*1000),round(duration*1000))
            active_seconds=time.monotonic()-started
            active_decoder_drops=last.get('dropped_bytes',0)
            # Use the native Recorder STOP, keep its forwarder/decoder alive,
            # and drain the PSRAM backlog before ending the SDK stream. The
            # unmodified SDK stop alone discards a slow radio's buffered tail.
            session=device._systemview_session
            device._bridge._write_raw(session._COMMAND_STOP)
            drain_start=time.monotonic();quiet_since=None
            while time.monotonic()-drain_start<45:
                batch=device.systemview_read(.1);consume(batch)
                # An empty local queue can coexist with a large BLE reply in
                # flight. The authenticated snapshot waits behind that owned
                # RPC and proves the device-side PSRAM FIFO is empty as well.
                measured=device._bridge.link.call('probe.metrics.snapshot')
                usb_pending_after_drain=measured['rx_pending']
                if batch.get('bytes_read',0) or usb_pending_after_drain:quiet_since=None
                elif quiet_since is None:quiet_since=time.monotonic()
                elif time.monotonic()-quiet_since>=1:break
            else:raise RuntimeError('Recorder tail did not quiesce within45seconds; capture incomplete')
            drain_seconds=time.monotonic()-drain_start
            radio_decoder_drops=last.get('dropped_bytes',0)
            parser=device._systemview_parser
        closed=True
        # Recorder STOP was already sent once above. Finish the forwarder with
        # the SDK's acknowledged text stop and identity, without issuing a
        # second binary STOP into a potentially restored Pika command parser.
        if not device._bridge._stop_stream_and_sync(b'SystemView.stop()\n'):
            device._bridge.link.poisoned=True
            raise RuntimeError('Native SystemView terminal synchronization failed; no reuse')
        session._running=False;session._prefetched.clear();session._tasklist_requested=False
        device._systemview_session=None;device._systemview_parser=None
        # V4 can stop its forwarder before the target's final TraceStop packet
        # is consumed. Drain that stopped recorder's channel via native MUX RTT,
        # without sending another Recorder START or inventing decoded events.
        with retained_rtt_tail(device,address):
            with path.open('a',encoding='utf-8') as sink:
                began=time.monotonic();quiet_since=None
                while time.monotonic()-began<15:
                    raw=device.rtt_read_channels(.1).get(1,b'')
                    if raw:
                        target_tail_bytes+=len(raw);quiet_since=None
                        consume(dict(events=parser.feed(raw),bytes_read=len(raw),synced=parser.synced,
                            cpu_freq=parser.cpu_freq,task_names=dict(parser._task_names),isr_names=dict(parser._isr_names),
                            dropped_bytes=parser.dropped_bytes,dropped_packets=parser.dropped_packets))
                    elif quiet_since is None:quiet_since=time.monotonic()
                    elif time.monotonic()-quiet_since>=.5:break
                else:raise RuntimeError('Stopped target Trace buffer did not quiesce')
        # ARM32 SEGGER_RTT.h: ID16 + two int counts, followed by24-byte UP
        # descriptors {name,buffer,size,WrOff,RdOff,flags}; channel1 at+48.
        header=device.read_memory(address,24)
        descriptor=device.read_memory(address+48,24)
        if len(header)!=24 or header[:11]!=b'SEGGER RTT\0' or struct.unpack_from('<I',header,16)[0]<2 or len(descriptor)!=24:
            raise RuntimeError('RTT control block changed during final Trace check')
        _,buffer,capacity,write,read,_=struct.unpack('<6I',descriptor)
        if not (RAM<=buffer<buffer+capacity<=RAM_END and write<capacity and read<capacity):
            raise RuntimeError('Invalid final target RTT descriptor')
        pending=(write-read)%capacity
        if pending or recording_stop_us is None:raise RuntimeError(f'Trace incomplete: target_pending={pending}, stop_marker={recording_stop_us is not None}, tail_bytes={target_tail_bytes}; raw capture={path}')
    finally:
        if not closed:device.systemview_stop()
    elapsed=time.monotonic()-started
    raw_span=(last_event_us-first_event_us)/1e6 if last_event_us is not None and first_event_us is not None else 0
    span=(recording_stop_us-recording_start_us)/1e6 if recording_stop_us is not None and recording_start_us is not None else 0
    return dict(native_systemview=True,rtos='FreeRTOS',task_name_source='SEGGER FreeRTOS task metadata; no RT-Thread TCB resolver',
                seconds=round(elapsed,3),capture_active_seconds=round(active_seconds,3),tail_drain_seconds=round(drain_seconds,3),
                setup_ms=round((started-setup_started)*1000,3),raw_target_span_seconds=round(raw_span,6),
                prefix_events=prefix_events,recording_events=recording_events,target_tail_bytes=target_tail_bytes,
                target_ring_pending=pending,trace_stop_verified=True,
                usb_pending_after_drain=usb_pending_after_drain,active_decoder_dropped_bytes=active_decoder_drops,
                stop_decoder_dropped_bytes=radio_decoder_drops-active_decoder_drops,
                target_tail_decoder_dropped_bytes=last.get('dropped_bytes',0)-radio_decoder_drops,
                target_span_seconds=round(span,6),events=events,bytes=data_bytes,events_s=round(events/elapsed,2),
                target_events_s=round(recording_events/span,2) if span>0 else None,bytes_s=round(data_bytes/elapsed,2),
                tail_drained=True,terminal_identity_verified=True,
                synced=last.get('synced',False),cpu_freq=last.get('cpu_freq'),task_names=last.get('task_names',{}),
                isr_names=last.get('isr_names',{}),dropped_bytes=last.get('dropped_bytes',0),dropped_packets=last.get('dropped_packets',0),
                event_types=event_types,preview=preview,start=info,capture_path=str(path),capture_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
