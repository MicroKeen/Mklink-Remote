import asyncio,json,struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'adapter'))
from mklink_remote.s3_ble import BleEndpoint,AESGCM
from mklink_remote.s3_transport import WirelessLink
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
 def test_ble_delivery_window_keeps_larger_http_window(self):
  def rpc(method,params):
   return {'get_status':{'device':{'id':'012345abcdef'},'probe':{'ready':True,'version':'V4.7.2'}},'control.acquire':{'lease_token':'test'},'get_probe_transport':{'binary_streaming':True,'stream_active':False,'state':'ready','generation':1,'next_sequence':0,'read_limit_supported':True,'max_read_payload':4096,'bulk_read_max':32768,'usb_metrics_supported':True,'file_chunk_max':2048}}[method]
  for cap,expected in ((None,32768),(4096,4096)):
   w=WirelessLink(rpc,'012345abcdef',read_window_cap=cap);w.acquire();self.assertEqual(w.read_max,expected)
if __name__=='__main__':unittest.main()
