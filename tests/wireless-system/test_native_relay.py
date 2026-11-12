"""Transport boundaries, using the installed native SDK without hardware."""
import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'desktop/mklink-wireless-config/adapter'))
from mklink_remote.s3_transport import WirelessLink,WirelessSerial,WirelessBridge
from mklink._types import DeviceState

class FakeRpc:
    def __init__(self):
        self.methods=[];self.writes=[];self.input=b'';self.fail_write=False;self.short_write=False;self.next=1;self.file=bytearray();self.renewals=0;self.upload_active=False
    def __call__(self,method,p):
        self.methods.append(method)
        if method=='get_status':return {'device':{'id':'020000123456'},'probe':{'ready':True}}
        if method=='control.acquire':return {'lease_token':'a'*32}
        if method=='control.release':return {}
        if method=='control.renew':self.renewals+=1;return {}
        if method=='get_probe_transport':return dict(binary_streaming=True,stream_active=False,state='ready',generation=7,next_sequence=self.next)
        if method.startswith('probe.stream.'):
            if method.endswith('abort'):return {}
            assert p['sequence']==self.next and p['generation']==7 and p['lease_token']=='a'*32
            self.next+=1;data=b'';count=0
            if method.endswith('write'):
                if self.fail_write:raise OSError('lost acknowledgement')
                chunk=base64.b64decode(p['request_base64']);self.writes.append(chunk);count=len(chunk)-(1 if self.short_write else 0)
            if method.endswith('read'):data=self.input;self.input=b''
            return dict(generation=7,reply_base64=base64.b64encode(data).decode(),accepted_bytes=count)
        if method=='probe.files.status':return dict(upload_active=self.upload_active,upload_id='session' if self.upload_active else '')
        if method=='probe.files.abort':
            assert p['upload_id']=='session';self.upload_active=False;return dict(aborted=True)
        if method=='probe.files.begin':self.sha=p['sha256'];self.upload_active=True;self.file.clear();return dict(complete=False,upload_id='session',offset=0)
        if method=='probe.files.write':
            assert p['offset']==len(self.file);self.file.extend(base64.b64decode(p['data_base64']));return dict(offset=len(self.file))
        if method=='probe.files.commit':self.upload_active=False;return dict(sha256=hashlib.sha256(self.file).hexdigest(),bytes=len(self.file),path='/WLINK/TEST.BIN')
        raise AssertionError(method)

class NativeRelayTests(unittest.TestCase):
    def test_recovery_waits_for_old_lease_then_acquires_once(self):
        class Expiring(FakeRpc):
            def __init__(self):super().__init__();self.status_reads=0;self.recovered=False
            def __call__(self,m,p):
                if m=='probe.recover':
                    self.methods.append(m);self.recovered=True
                    return dict(generation=8,old_outcome_resolved=False)
                value=super().__call__(m,p)
                if m=='get_status':
                    self.status_reads+=1
                    value['control']={'owner':'old' if self.status_reads<3 else '', 'busy':False}
                    value['probe']['ready']=self.recovered
                if m=='get_probe_transport':value.update(state='ready' if self.recovered else 'outcome_unknown',generation=8 if self.recovered else 7,mux_recovery_supported=True,mux_recoverable=True)
                return value
        rpc=Expiring();link=WirelessLink(rpc,'020000123456')
        with patch('mklink_remote.s3_transport.time.sleep') as sleep:link.acquire()
        self.assertEqual(sleep.call_count,2)
        self.assertEqual(rpc.methods.count('control.acquire'),1)
        self.assertEqual(rpc.methods.count('probe.recover'),1)
        self.assertEqual(rpc.writes,[])
        link.close()

    def test_live_or_busy_owner_is_never_taken_over(self):
        for dirty,busy,recover in [(False,False,True),(True,True,True),(True,False,False)]:
            class Occupied(FakeRpc):
                def __call__(self,m,p):
                    value=super().__call__(m,p)
                    if m=='get_status':value['control']={'owner':'other','busy':busy}
                    if m=='get_probe_transport':value.update(state='outcome_unknown' if dirty else 'ready',mux_recovery_supported=True,mux_recoverable=True)
                    return value
            rpc=Occupied()
            with patch('mklink_remote.s3_transport.time.sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError,'still held'):WirelessLink(rpc,'020000123456').acquire(recover_stream=recover)
                sleep.assert_not_called()
            self.assertNotIn('control.acquire',rpc.methods)
            self.assertNotIn('probe.recover',rpc.methods)

    def test_renewed_quarantined_owner_has_bounded_wait(self):
        class Occupied(FakeRpc):
            def __call__(self,m,p):
                value=super().__call__(m,p)
                if m=='get_status':value['control']={'owner':'other','busy':False}
                if m=='get_probe_transport':value.update(state='outcome_unknown',mux_recovery_supported=True,mux_recoverable=True)
                return value
        rpc=Occupied();link=WirelessLink(rpc,'020000123456')
        with patch('mklink_remote.s3_transport.time.monotonic',side_effect=[0,0,17]), patch('mklink_remote.s3_transport.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'still held'):link.acquire()
        self.assertNotIn('control.acquire',rpc.methods)

    def test_new_connection_recovers_known_mux_once_without_replaying(self):
        class Recover(FakeRpc):
            def __init__(self):super().__init__();self.recovered=False
            def __call__(self,method,p):
                if method=='probe.recover':
                    self.methods.append(method);assert p['generation']==7
                    self.recovered=True;return dict(generation=8,old_outcome_resolved=False)
                value=super().__call__(method,p)
                if method=='get_status':value['probe']['ready']=self.recovered
                if method=='get_probe_transport':value.update(state='ready' if self.recovered else 'outcome_unknown',generation=8 if self.recovered else 7,mux_recovery_supported=True,mux_recoverable=True)
                return value
        rpc=Recover();link=WirelessLink(rpc,'020000123456');link.acquire()
        self.assertEqual(link.generation,8);self.assertEqual(rpc.methods.count('probe.recover'),1)
        self.assertEqual(rpc.writes,[]);link.close()
    def test_unknown_legacy_stream_never_attempts_mux_recovery(self):
        class Legacy(FakeRpc):
            def __call__(self,m,p):
                v=super().__call__(m,p)
                if m=='get_status':v['probe']['ready']=False
                if m=='get_probe_transport':v.update(state='outcome_unknown',mux_recovery_supported=True,mux_recoverable=False)
                return v
        rpc=Legacy()
        with self.assertRaises(RuntimeError):WirelessLink(rpc,'020000123456').acquire()
        self.assertNotIn('control.acquire',rpc.methods);self.assertNotIn('probe.recover',rpc.methods)
    def test_negotiated_psram_window_preserves_unconsumed_native_bytes(self):
        class Extended(FakeRpc):
            def __call__(self,method,params):
                value=super().__call__(method,params)
                if method=='get_probe_transport':value.update(read_limit_supported=True,max_read_payload=4096,file_chunk_max=2048)
                if method=='probe.stream.read':self.asserted_limit=params['max_bytes']
                return value
        rpc=Extended();link=WirelessLink(rpc,'020000123456');link.acquire();serial=WirelessSerial(link)
        rpc.input=bytes(range(256))*16
        self.assertEqual(serial.read(1024),bytes(range(256))*4);self.assertEqual(serial.in_waiting,3072)
        self.assertEqual(serial.read(3072),bytes(range(256))*12);self.assertEqual(rpc.asserted_limit,4096)
        serial.close();link.close()
    def test_negotiated_file_chunks_keep_exact_offsets_and_full_digest(self):
        class Extended(FakeRpc):
            def __call__(self,method,params):
                value=super().__call__(method,params)
                if method=='get_probe_transport':value.update(file_chunk_max=2048)
                if method=='probe.files.write':self.sizes.append(len(base64.b64decode(params['data_base64'])))
                return value
        rpc=Extended();rpc.sizes=[];link=WirelessLink(rpc,'020000123456');link.acquire()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'payload.bin';p.write_bytes(b'a'*4097);link.upload_file(p,'BIN')
        self.assertEqual(rpc.sizes,[2048,2048,1]);self.assertEqual(bytes(rpc.file),b'a'*4097);link.close()
    def test_native_deadline_covers_radio_rpc_and_preserves_long_flash_budget(self):
        link=WirelessLink(FakeRpc(),'020000123456');bridge=WirelessBridge(link)
        bridge._ctx.state=DeviceState.READY
        bridge._serial=Mock()
        for requested,respond_after in ((10,30),(600,90)):
            clock=[0.0]
            def wait(timeout):
                clock[0]+=1
                if clock[0]>=respond_after:
                    bridge._response_buffer.append('OK\n>>> ')
                    return True
                return False
            bridge._prompt_event=Mock(wait=wait)
            with patch('mklink.bridge.time.monotonic',side_effect=lambda:clock[0]):
                self.assertIn('OK',bridge.send_command('query',timeout=requested))
        self.assertEqual(bridge._serial.write.call_count,2)
    def test_native_timeout_is_not_retried_and_records_only_rpc_metadata(self):
        link=WirelessLink(FakeRpc(),'020000123456');bridge=WirelessBridge(link)
        link.recent_rpc.append(dict(method='probe.stream.read',ms=12000,ok=True))
        with patch('mklink.bridge.MKLinkSerialBridge.send_command',side_effect=TimeoutError('timeout')) as send:
            with self.assertRaises(TimeoutError) as error:bridge.send_command('cmd.read_ram(0,4)')
        send.assert_called_once();self.assertIn('probe.stream.read',str(error.exception.__notes__))
    def test_ble_heartbeat_tracking_does_not_reserve_command_slot(self):
        bridge = WirelessBridge(self.link)
        self.assertFalse(self.link.duplex)
        self.assertTrue(bridge.mux_background_heartbeats)

    def test_reply_observer_handles_fragmentation_and_crc_without_changing_bytes(self):
        from mklink.mux import packet
        serial = WirelessSerial(self.link)
        good = packet(0xB5, 7, 12, b'\0abcd')
        bad = good[:-1] + bytes([good[-1] ^ 1])
        with patch('mklink.connection_diagnostics.event') as event:
            serial._observe_replies(bad + good[:11])
            event.assert_not_called()
            serial._observe_replies(good[11:])
            event.assert_called_once_with('remote.mux_reply', opcode=0xB5, epoch=7, request=12, status=0)
        self.assertEqual(serial._trace_rx, b'')
        serial.close();self.link.close()

    def setUp(self):self.rpc=FakeRpc();self.link=WirelessLink(self.rpc,'020000123456');self.link.acquire()
    def test_binary_receive_is_not_decoded_or_discarded(self):
        s=WirelessSerial(self.link);self.rpc.input=b'\0\xffMLX1\r\n>>>'
        self.assertEqual(s.read(2),b'\0\xff');self.assertEqual(s.read(100),b'MLX1\r\n>>>');s.close();self.link.close()
    def test_file_packet_chunking_preserves_exact_bytes(self):
        s=WirelessSerial(self.link);data=bytes(range(256))*4+b'abcde';self.assertEqual(s.write(data),1029)
        self.assertEqual(list(map(len,self.rpc.writes)),[1024,5]);self.assertEqual(b''.join(self.rpc.writes),data);s.close();self.link.close()
    def test_lost_write_ack_is_never_retried(self):
        s=WirelessSerial(self.link);self.rpc.fail_write=True
        with self.assertRaises(ConnectionError):s.write(b'once')
        with self.assertRaises(ConnectionError):s.write(b'once')
        self.assertEqual(self.rpc.methods.count('probe.stream.write'),1)
        with self.assertRaises(ConnectionError):self.link.close()
        self.assertIn('probe.stream.abort',self.rpc.methods)
    def test_partial_write_poisons_session(self):
        s=WirelessSerial(self.link);self.rpc.short_write=True
        with self.assertRaises(ConnectionError):s.write(b'ab')
        self.assertTrue(self.link.poisoned)
    def test_failed_native_exit_does_not_close_as_clean(self):
        s=WirelessSerial(self.link);s.safe_close=lambda:False;s.close()
        self.assertTrue(self.link.poisoned);self.assertNotIn('probe.stream.close',self.rpc.methods)
    def test_native_pika_error_state_cannot_close_as_clean(self):
        bridge=WirelessBridge(self.link);bridge._serial=WirelessSerial(self.link);bridge._ctx.state=DeviceState.ERROR
        bridge.close()
        self.assertTrue(self.link.poisoned);self.assertNotIn('probe.stream.close',self.rpc.methods)
        with self.assertRaises(ConnectionError):self.link.close()
    def test_timeout_does_not_replay_file_chunk(self):
        original=self.link.rpc
        def fail(method,p):
            if method=='probe.files.write':self.rpc.methods.append(method);raise TimeoutError('lost response')
            return original(method,p)
        self.link.rpc=fail
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.bin';p.write_bytes(b'abc')
            with self.assertRaises(TimeoutError):self.link.upload_file(p,'BIN')
        self.assertEqual(self.rpc.methods.count('probe.files.write'),1);self.assertNotIn('probe.files.commit',self.rpc.methods)
    def test_full_file_commit_verifies_digest_and_length(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.bin';data=b'abc'*700;p.write_bytes(data)
            self.assertEqual(self.link.upload_file(p,'BIN'),'/WLINK/TEST.BIN');self.assertEqual(bytes(self.rpc.file),data)

    def test_lost_staging_replies_clean_only_temporary_upload_without_replay(self):
        for failed in ('begin','write','commit'):
            with self.subTest(failed=failed),tempfile.TemporaryDirectory() as folder:
                class Lost(FakeRpc):
                    armed=True
                    def __call__(self,method,p):
                        value=super().__call__(method,p)
                        if self.armed and method=='probe.files.'+failed:
                            self.armed=False;raise TimeoutError('lost '+failed)
                        return value
                rpc=Lost();link=WirelessLink(rpc,'020000123456');link.acquire()
                p=Path(folder)/'test.bin';p.write_bytes(b'original')
                with self.assertRaisesRegex(TimeoutError,'lost '+failed):link.upload_file(p,'BIN')
                self.assertFalse(rpc.upload_active)
                self.assertEqual(rpc.methods.count('probe.files.'+failed),1)
                self.assertEqual(rpc.methods.count('probe.files.abort'),0 if failed=='commit' else 1)
                self.assertEqual(rpc.writes,[])
                self.assertEqual(link.upload_file(p,'BIN'),'/WLINK/TEST.BIN')
                link.close()

    def test_unconfirmed_upload_cleanup_keeps_original_error_and_never_retries(self):
        class Lost(FakeRpc):
            def __call__(self,method,p):
                value=super().__call__(method,p)
                if method in ('probe.files.write','probe.files.abort'):raise TimeoutError(method)
                return value
        rpc=Lost();link=WirelessLink(rpc,'020000123456');link.acquire()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.bin';p.write_bytes(b'original')
            with self.assertRaisesRegex(RuntimeError,'probe.files.write; upload cleanup unconfirmed: probe.files.abort'):
                link.upload_file(p,'BIN')
        self.assertEqual(rpc.methods.count('probe.files.write'),1)
        self.assertEqual(rpc.methods.count('probe.files.abort'),1)
        self.assertNotIn('probe.files.commit',rpc.methods)
        link.close()

    def test_preexisting_or_changed_upload_is_never_aborted(self):
        for preexisting in (True,False):
            with self.subTest(preexisting=preexisting),tempfile.TemporaryDirectory() as folder:
                class Other(FakeRpc):
                    def __call__(self,method,p):
                        value=super().__call__(method,p)
                        if method=='probe.files.write':raise TimeoutError('lost write')
                        if method=='probe.files.status' and self.upload_active:value['upload_id']='other'
                        return value
                rpc=Other();rpc.upload_active=preexisting
                link=WirelessLink(rpc,'020000123456');link.acquire()
                p=Path(folder)/'test.bin';p.write_bytes(b'original')
                with self.assertRaises(RuntimeError):link.upload_file(p,'BIN')
                self.assertNotIn('probe.files.abort',rpc.methods)
                if preexisting:self.assertNotIn('probe.files.begin',rpc.methods)
                link.close()

    def test_upload_validation_failure_does_not_commit_or_remove_completed_files(self):
        for fault in ('offset','digest','cached_digest'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as folder:
                class Invalid(FakeRpc):
                    def __call__(self,method,p):
                        value=super().__call__(method,p)
                        if fault=='offset' and method=='probe.files.write':value['offset']+=1
                        if fault=='digest' and method=='probe.files.commit':value['sha256']='0'*64
                        if fault=='cached_digest' and method=='probe.files.begin':
                            self.upload_active=False;value=dict(complete=True,sha256='0'*64,path='/WLINK/OLD.BIN')
                        return value
                rpc=Invalid();link=WirelessLink(rpc,'020000123456');link.acquire()
                p=Path(folder)/'test.bin';p.write_bytes(b'original')
                with self.assertRaises(RuntimeError):link.upload_file(p,'BIN')
                self.assertEqual(rpc.methods.count('probe.files.abort'),1 if fault=='offset' else 0)
                self.assertEqual(rpc.methods.count('probe.files.commit'),1 if fault=='digest' else 0)
                link.close()

    def test_upload_status_failure_stops_and_reports_unconfirmed_cleanup(self):
        for initial in (True,False):
            with self.subTest(initial=initial),tempfile.TemporaryDirectory() as folder:
                class Unavailable(FakeRpc):
                    def __call__(self,method,p):
                        value=super().__call__(method,p)
                        if method=='probe.files.status' and (initial or self.upload_active):raise TimeoutError('status unavailable')
                        if method=='probe.files.write':raise TimeoutError('lost write')
                        return value
                rpc=Unavailable();link=WirelessLink(rpc,'020000123456');link.acquire()
                p=Path(folder)/'test.bin';p.write_bytes(b'original')
                with self.assertRaisesRegex(TimeoutError if initial else RuntimeError,'status unavailable'):
                    link.upload_file(p,'BIN')
                self.assertEqual(rpc.methods.count('probe.files.begin'),0 if initial else 1)
                self.assertNotIn('probe.files.abort',rpc.methods)
                link.close()

    def test_upload_serialization_leaves_native_io_and_renewal_available(self):
        rpc=FakeRpc();link=WirelessLink(rpc,'020000123456');link.acquire()
        paused=threading.Event();release=threading.Event();errors=[]
        def progress(phase,done,total):
            if phase=='upload' and done:
                paused.set()
                if not release.wait(2):raise TimeoutError('test release')
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.bin';p.write_bytes(b'original')
            def upload():
                try:link.upload_file(p,'BIN',progress=progress)
                except BaseException as error:errors.append(error)
            worker=threading.Thread(target=upload);worker.start()
            try:
                self.assertTrue(paused.wait(2))
                self.assertFalse(link.upload_lock.acquire(blocking=False))
                link.renewed-=4;link.renew_if_due()
                self.assertEqual(rpc.renewals,1)
                link.stream('write',b'native-reader-heartbeat')
                self.assertEqual(rpc.writes,[b'native-reader-heartbeat'])
            finally:
                release.set();worker.join(3)
            self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        link.close()
    def test_file_progress_reports_acknowledged_offsets_and_separate_verification(self):
        events=[]
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.bin';p.write_bytes(b'x'*1500)
            self.link.upload_file(p,'BIN',progress=lambda *event:events.append(event))
        self.assertEqual(events,[('upload',0,1500),('upload',1024,1500),('upload',1500,1500),('verify',0,0),('complete',1500,1500)])
    def test_changed_staging_input_is_rejected_before_any_file_rpc(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.bin';p.write_bytes(b'changed')
            with self.assertRaises(RuntimeError):self.link.upload_file(p,'BIN',expected_sha256='0'*64)
        self.assertNotIn('probe.files.begin',self.rpc.methods)
    def test_renewal_is_shared_with_native_reader(self):
        self.link.renewed-=4;s=WirelessSerial(self.link);self.assertEqual(self.rpc.renewals,1);s.close();self.link.close()
    def test_invalid_identity_fails_before_rpc(self):
        with self.assertRaises(ValueError):WirelessLink(self.rpc,'wrong')
    def test_continuous_empty_reads_do_not_starve_native_writer(self):
        s=WirelessSerial(self.link);stop=threading.Event();polling=threading.Event();errors=[]
        def poll():
            try:
                while not stop.is_set():s.read(1024);polling.set()
            except Exception as e:errors.append(e)
        reader=threading.Thread(target=poll);reader.start();self.assertTrue(polling.wait(1))
        writer=threading.Thread(target=lambda:s.write(b'bounded-writer'))
        try:
            writer.start();writer.join(2)
            self.assertFalse(writer.is_alive(),'Polling must admit a queued native command before its deadline')
            self.assertIn(b'bounded-writer',self.rpc.writes)
        finally:
            stop.set();reader.join(2);writer.join(2);s.close();self.link.close()
        self.assertEqual(errors,[])

if __name__=='__main__':unittest.main()
