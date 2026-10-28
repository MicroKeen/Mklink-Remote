"""Transport boundaries, using the installed native SDK without hardware."""
import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'desktop/mklink-wireless-config/tools'))
from mklink_wireless import WirelessLink,WirelessSerial,WirelessBridge
from mklink._types import DeviceState

class FakeRpc:
    def __init__(self):
        self.methods=[];self.writes=[];self.input=b'';self.fail_write=False;self.short_write=False;self.next=1;self.file=bytearray();self.renewals=0
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
        if method=='probe.files.begin':self.sha=p['sha256'];return dict(complete=False,upload_id='session',offset=0)
        if method=='probe.files.write':
            assert p['offset']==len(self.file);self.file.extend(base64.b64decode(p['data_base64']));return dict(offset=len(self.file))
        if method=='probe.files.commit':return dict(sha256=hashlib.sha256(self.file).hexdigest(),bytes=len(self.file),path='/WLINK/TEST.BIN')
        raise AssertionError(method)

class NativeRelayTests(unittest.TestCase):
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
        with patch('mklink.bridge.MKLinkSerialBridge.send_command',return_value='ok') as send:
            self.assertEqual(bridge.send_command('cmd.read_ram(0,4)',timeout=10),'ok')
            self.assertEqual(send.call_args.kwargs['timeout'],60)
            bridge.send_command('cmd.long_operation()',timeout=600)
            self.assertEqual(send.call_args.kwargs['timeout'],600)
    def test_native_timeout_is_not_retried_and_records_only_rpc_metadata(self):
        link=WirelessLink(FakeRpc(),'020000123456');bridge=WirelessBridge(link)
        link.recent_rpc.append(dict(method='probe.stream.read',ms=12000,ok=True))
        with patch('mklink.bridge.MKLinkSerialBridge.send_command',side_effect=TimeoutError('timeout')) as send:
            with self.assertRaises(TimeoutError) as error:bridge.send_command('cmd.read_ram(0,4)')
        send.assert_called_once();self.assertIn('probe.stream.read',str(error.exception.__notes__))
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
