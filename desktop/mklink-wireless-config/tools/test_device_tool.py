import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import device_tool as tool


class FirmwareSafetyTests(unittest.TestCase):
    def package(self, folder):
        images = []
        for address in [0,0x8000,0x9000,0x10000]:
            f=folder/f'{address:x}.bin';f.write_bytes(b'x'*16)
            images.append(dict(address=address,file=f.name,bytes=16,sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
        p=folder/'manifest.json';p.write_text(json.dumps(dict(project='n16r8_wireless_gateway',target='esp32s3',flash_bytes=tool.TOTAL,version='test',images=images)))
        return p
    def test_corrupt_wrong_board_and_overlapping_images_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.package(Path(d));tool.load_images(p)
            m=json.loads(p.read_text());m['target']='esp32';p.write_text(json.dumps(m))
            with self.assertRaises(ValueError):tool.load_images(p)
            p=self.package(Path(d));m=json.loads(p.read_text());m['images'][1]['address']=1;p.write_text(json.dumps(m))
            with self.assertRaises(ValueError):tool.load_images(p)
            p=self.package(Path(d));(Path(d)/'10000.bin').write_bytes(b'changed')
            with self.assertRaises(ValueError):tool.load_images(p)
    def test_path_escape_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.package(Path(d));m=json.loads(p.read_text());m['images'][0]['file']='../outside.bin';p.write_text(json.dumps(m))
            with self.assertRaises(ValueError):tool.load_images(p)
    def test_native_read_length_digest_and_proven_blank_regions(self):
        class Esp:
            payload=b'x'*512
            reads=0
            def flash_md5sum(self,*args):return hashlib.md5(self.payload).hexdigest()
            def read_flash(self,*args):self.reads+=1;return self.received
        e=Esp();e.received=b'x'*511
        with self.assertRaises(RuntimeError):tool.read_segment(e,0,512)
        e.received=b'y'*512
        with self.assertRaises(RuntimeError):tool.read_segment(e,0,512)
        e.received=e.payload
        self.assertEqual(len(tool.read_segment(e,0,512)),512)
        e.payload=b'\xff'*512;e.received=b'bad';before=e.reads
        self.assertEqual(tool.read_segment(e,0,512),e.payload);self.assertEqual(e.reads,before)
        with self.assertRaises(ValueError):tool.read_segment(e,tool.TOTAL-1,512)
    def test_backup_failure_never_calls_write(self):
        class Esp:
            _port=type('Port',(),{'close':lambda self:None})()
        with tempfile.TemporaryDirectory() as d:
            p=self.package(Path(d));backups=Path(d)/'backups'
            with patch.object(tool,'connect',return_value=(Esp(),'02:00:00:12:34:56')),patch.object(tool,'read_segment',side_effect=RuntimeError('short frame')),patch.object(tool.cmds,'write_flash') as write,patch.object(tool,'emit'):
                with self.assertRaises(RuntimeError):tool.install('test-port',p,backups)
                write.assert_not_called()
                journal=json.loads(next(backups.glob('*.json')).read_text(encoding='utf-8'))
                self.assertFalse(journal['flash_started'])
                self.assertFalse(journal['backup_complete'])

if __name__=='__main__':unittest.main()
