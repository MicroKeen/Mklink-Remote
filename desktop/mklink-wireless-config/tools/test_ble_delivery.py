import asyncio,json,struct,sys,unittest
import threading,time
import base64,zlib
from unittest.mock import Mock,patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'adapter'))
from mklink_remote.s3_ble import BleEndpoint,AESGCM
from mklink_remote.s3_transport import WirelessLink,WirelessBridge
from mklink.mux import MuxTransport
class FakeGatt:
 mtu_size=247
 def __init__(self,ep):self.ep=ep;self.writes=0;self.reads=0;self.packet=None
 async def write_gatt_char(self,char,packet,response):
  self.writes+=1;body=packet[6:];seq=body[:4]
  req=json.loads(AESGCM(self.ep.key).decrypt(body[4:16],body[16:],b'mklink-ble-request-v1'+seq))
  plain=json.dumps({'v':1,'id':req['id'],'ok':True,'data':{'ready':True}}).encode();nonce=b'0'*12
  self.packet=seq+nonce+AESGCM(self.ep.key).encrypt(nonce,plain,b'mklink-ble-response-v1'+seq)
 async def read_gatt_char(self,char):
  self.reads+=1
  if self.reads==3:self.ep._notify(None,struct.pack('<HHH',self.ep.message_id,0,len(self.packet))+self.packet)
  return self.ep.session_info
class BLEDrainTest(unittest.IsolatedAsyncioTestCase):
 async def test_late_notification_drains_without_resubmission(self):
  e=BleEndpoint('test','00'*16);e.key=b'1'*16;e.session_info=b'2'*17;e.client=FakeGatt(e)
  self.assertEqual(await e.rpc('get_status',timeout=2),{'ready':True})
  self.assertEqual(e.client.writes,1);self.assertEqual(e.client.reads,3)
class WindowTest(unittest.TestCase):
 def test_duplex_heartbeat_survives_blocked_reader_in_idle_rtt_and_watch(self):
  for duplex,watch,rtt in ((d,w,r) for d in (False,True) for w,r in ((False,0),(False,1),(True,0))):
   with self.subTest(duplex=duplex,watch=watch,rtt=rtt):
    writes=[];workers=[]
    link=Mock(node_id='012345abcdef',duplex=duplex)
    bridge=WirelessBridge(link)
    bridge._hil_locks=[];bridge._port_lock=Mock()
    bridge._lease_stop=Mock();bridge._lease_stop.wait.side_effect=[False,True]
    bridge._prompt_event=Mock();bridge._verify_identity=Mock(return_value=True)
    mux=MuxTransport(writes.append);mux.ready=True;mux.epoch=7
    mux.watch_running=watch;mux.rtt_mask=rtt
    bridge._mux=mux
    def thread(*,target,**kwargs):
     workers.append(target);return Mock()
    with patch('mklink.probes.require_runtime_port'),patch('mklink_remote.s3_transport.WirelessSerial'),patch('mklink_remote.s3_transport.threading.Thread',side_effect=thread):
     bridge._connect()
    self.assertTrue(bridge.mux_background_heartbeats)
    mux.background_heartbeats=bridge.mux_background_heartbeats
    # Leave the sole reader blocked: only the independent timer can send.
    with patch('mklink.mux.time.monotonic',return_value=mux._last_command+1.1):
     workers[0]()
    self.assertEqual(len(writes),1)
    self.assertIsNone(mux._pending)
    self.assertEqual(len(mux._heartbeats),1)
 def test_lossless_wifi_pull_rejects_truncation_trailing_data_and_expansion(self):
  original=b'\x00\xffMLX1'*150
  packed=zlib.compress(original)
  for content,size,negotiated,ok in [
      (packed,len(original),True,True),(packed[:-2],len(original),True,False),
      (packed+b'x',len(original),True,False),(packed,128,True,False),
      (packed,len(original),False,False)]:
   pull=Mock(return_value={'generation':7,'reply_zlib_base64':base64.b64encode(content).decode(),'uncompressed_bytes':size})
   link=WirelessLink(Mock(),'012345abcdef',pull_rpc=pull)
   link.opened=True;link.open_sequence=4;link.generation=7;link.lease='test';link.renewed=time.monotonic()
   link.duplex=True;link.zlib_pull=negotiated
   if ok:
    self.assertEqual(link.stream('read',interactive=True),original)
    self.assertEqual((link.pull_native_bytes,link.pull_encoded_bytes),(len(original),len(packed)))
   else:
    with self.assertRaises(ConnectionError):link.stream('read',interactive=True)
    self.assertTrue(link.poisoned)
   pull.assert_called_once()
 def test_wifi_pull_uses_negotiated_32k_without_losing_bytes(self):
  data=bytes(range(256))*128
  pull=Mock(return_value={'generation':7,'reply_base64':base64.b64encode(data).decode()})
  link=WirelessLink(Mock(),'012345abcdef',pull_rpc=pull)
  link.opened=True;link.open_sequence=4;link.generation=7;link.lease='test';link.renewed=time.monotonic()
  link.duplex=True;link.read_max=32768
  self.assertEqual(link.stream('read',interactive=True),data)
  self.assertEqual(pull.call_args.args[1]['max_bytes'],32768)
  link.read_max=4096
  with self.assertRaises(ConnectionError):link.stream('read',interactive=True)
  self.assertTrue(link.poisoned)
 def test_ble_compression_requires_capability_and_exact_bounded_stream(self):
  data=bytes(range(256))*16;packed=zlib.compress(data)
  good={'generation':7,'uncompressed_bytes':4096,'reply_zlib_base64':base64.b64encode(packed).decode()}
  cases=[(good,True,True),(good,False,False)]
  for extra in [{'uncompressed_bytes':True},{'uncompressed_bytes':4097},{'uncompressed_bytes':4000},
                {'reply_base64':''},{'reply_zlib_base64':base64.b64encode(packed[:-1]).decode()},
                {'reply_zlib_base64':base64.b64encode(packed+b'x').decode()}]:
   cases.append((dict(good,**extra),True,False))
  for response,negotiated,valid in cases:
   rpc=Mock(return_value=response);link=WirelessLink(rpc,'012345abcdef')
   link.lease='test';link.renewed=time.monotonic();link.generation=7;link.sequence=1;link.read_max=4096;link.zlib_reads=negotiated
   if valid:self.assertEqual(link.stream('read',interactive=True),data)
   else:
    with self.assertRaises(ConnectionError):link.stream('read',interactive=True)
    self.assertTrue(link.poisoned)
   rpc.assert_called_once()
   self.assertEqual(rpc.call_args.args[1].get('accept_zlib',False),negotiated)
 def test_large_ble_window_is_enabled_only_with_lossless_capability(self):
  for zipped,expected in ((False,4096),(True,16384)):
   def rpc(method,params):
    return {'get_status':{'device':{'id':'012345abcdef'},'probe':{'ready':True}},'control.acquire':{'lease_token':'test'},
            'get_probe_transport':{'binary_streaming':True,'stream_active':False,'state':'ready','generation':7,'next_sequence':1,
             'read_limit_supported':True,'max_read_payload':4096,'bulk_read_max':32768,'zlib_read_supported':zipped},
            'probe.stream.read':{'generation':7,'reply_base64':''}}[method]
   control=Mock(side_effect=rpc);link=WirelessLink(control,'012345abcdef',read_window_cap=16384);link.acquire()
   link.stream('read',interactive=True)
   self.assertEqual(control.call_args.args[1]['max_bytes'],expected)
 def test_control_can_finish_while_sample_delivery_is_blocked(self):
  waiting,release=threading.Event(),threading.Event()
  def pull(method,params):
   self.assertEqual((method,params['open_sequence'],params['sequence']),('probe.stream.pull',11,1))
   waiting.set()
   if not release.wait(2):raise RuntimeError('control starved')
   return {'generation':7,'reply_base64':'YQ=='}
  control=Mock(return_value={'generation':7,'reply_base64':'','accepted_bytes':1})
  link=WirelessLink(control,'012345abcdef',pull_rpc=pull)
  link.lease='test';link.renewed=time.monotonic();link.generation=7;link.sequence=12
  link.opened=True;link.open_sequence=11;link.duplex=True
  result=[]
  reader=threading.Thread(target=lambda:result.append(link.stream('read',interactive=True)))
  reader.start()
  try:
   self.assertTrue(waiting.wait(1))
   link.stream('write',b'x');self.assertEqual(control.call_args.args[1]['sequence'],12)
   with self.assertRaisesRegex(ConnectionError,'reader still owns'):link.stream('close')
  finally:
   release.set();reader.join(3)
  self.assertEqual(result,[b'a'])
 def test_interactive_reads_yield_and_only_negotiated_streams_refresh_lease(self):
  for renews in (True,False):
   rpc=Mock(return_value={'generation':1,'reply_base64':''})
   link=WirelessLink(rpc,'012345abcdef')
   link.generation=1;link.lease='test';link.sequence=1;link.renewed=2
   link.stream_renews_lease=renews;link.read_limit_supported=True;link.read_max=32768
   with patch('mklink_remote.s3_transport.time.monotonic',return_value=4):
    link.stream('read',interactive=True)
    self.assertEqual(rpc.call_args.args[1]['max_bytes'],4096)
   with patch('mklink_remote.s3_transport.time.monotonic',return_value=6):
    link.renew_if_due()
    self.assertEqual(rpc.call_args.args[0],'probe.stream.read' if renews else 'control.renew')
    link.stream('read')
    self.assertEqual(rpc.call_args.args[1]['max_bytes'],32768)
 def test_ble_delivery_window_keeps_larger_http_window(self):
  def rpc(method,params):
   return {'get_status':{'device':{'id':'012345abcdef'},'probe':{'ready':True,'version':'V4.7.2'}},'control.acquire':{'lease_token':'test'},'get_probe_transport':{'binary_streaming':True,'stream_active':False,'state':'ready','generation':1,'next_sequence':0,'read_limit_supported':True,'max_read_payload':4096,'bulk_read_max':32768,'usb_metrics_supported':True,'file_chunk_max':2048}}[method]
  for cap,expected in ((None,32768),(4096,4096)):
   w=WirelessLink(rpc,'012345abcdef',read_window_cap=cap);w.acquire();self.assertEqual(w.read_max,expected)
if __name__=='__main__':unittest.main()
