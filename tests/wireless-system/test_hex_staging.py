"""Real adapter staging; only radio RPC is replaced. No target operations."""
import hashlib
import base64
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
from intelhex import IntelHex
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'desktop/mklink-wireless-config/adapter'))
from mklink_remote.s3_transport import WirelessBridge,WirelessLink

class HexStaging(unittest.TestCase):
    def test_hex_file_rpc_preserves_payload_and_commits_digest(self):
        data=b':0100000012ED\n:00000001FF\n';digest=hashlib.sha256(data).hexdigest()
        link=WirelessLink(Mock(),'020000123456');link.hex_files_supported=True;link.file_chunk=10
        received=bytearray();calls=[]
        def call(method,params=None):
            calls.append(method)
            if method=='probe.files.status':return {'upload_active':False}
            if method=='probe.files.begin':
                self.assertEqual(params,{'kind':'HEX','size':len(data),'sha256':digest})
                return {'complete':False,'upload_id':'test'}
            self.assertEqual(params['upload_id'],'test')
            if method=='probe.files.write':
                self.assertEqual(params['offset'],len(received))
                received.extend(base64.b64decode(params['data_base64']))
                return {'offset':len(received)}
            self.assertEqual(method,'probe.files.commit')
            return {'bytes':len(received),'sha256':hashlib.sha256(received).hexdigest(),'path':'/WLINK/TEST.HEX'}
        link.call=call
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'firmware.hex';p.write_bytes(data)
            self.assertEqual(link.upload_file(p,'HEX',expected_sha256=digest),'/WLINK/TEST.HEX')
        self.assertEqual(bytes(received),data)
        self.assertEqual(calls.count('probe.files.commit'),1)
    def test_sparse_hex_preserves_original_bytes_addresses_and_hash(self):
        image=IntelHex();image[0x0800c000]=0x12;image[0x08010000]=0x34
        out=StringIO();image.write_hex_file(out);data=out.getvalue().encode('ascii')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'firmware.hex';p.write_bytes(data)
            link=Mock(node_id='020000123456');link.upload_file.return_value='/WLINK/TEST.HEX'
            bridge=WirelessBridge(link);bridge.prepare_firmware(p)
            link.upload_file.assert_called_once_with(p.resolve(),'HEX',expected_sha256=hashlib.sha256(data).hexdigest())
            self.assertEqual(bridge.upload_firmware(p),'/WLINK/TEST.HEX')
            self.assertEqual(p.read_bytes(),data)
            p.write_bytes(data+b'changed')
            with self.assertRaises(RuntimeError):bridge.upload_firmware(p)
    def test_invalid_and_empty_hex_never_stage(self):
        for data in [b':0100000012FF\n:00000001FF\n', b':00000001FF\n',b'not hex']:
            with self.subTest(data=data),tempfile.TemporaryDirectory() as d:
                p=Path(d)/'bad.hex';p.write_bytes(data)
                link=Mock(node_id='020000123456');bridge=WirelessBridge(link)
                with self.assertRaises(Exception):bridge.prepare_firmware(p)
                link.upload_file.assert_not_called()
    def test_old_gateway_rejects_hex_before_any_rpc(self):
        rpc=Mock();link=WirelessLink(rpc,'020000123456')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'firmware.hex';p.write_bytes(b':00000001FF\n')
            with self.assertRaisesRegex(ValueError,'update the gateway'):link.upload_file(p,'HEX')
        rpc.assert_not_called()
    def test_bin_remains_supported(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'firmware.bin';p.write_bytes(b'\0\x01\xFF')
            link=Mock(node_id='020000123456');bridge=WirelessBridge(link);bridge.prepare_firmware(p)
            self.assertEqual(link.upload_file.call_args.args[1],'BIN')

if __name__=='__main__':unittest.main()
