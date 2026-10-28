"""Reject unsafe regions/artifacts before invoking native target operations."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'desktop/mklink-wireless-config/tools'))
from target_ops import APP,END,FLASH,RAM,RAM_END,checked_range,prepare_internal_image,flash_application,verify_programmed_application,capture_rtt,read_flash_range

class Segment(dict):
    def __init__(self,address,data):super().__init__(p_type='PT_LOAD',p_paddr=address,p_filesz=len(data));self.bytes=data
    def data(self):return self.bytes
class Elf:
    def __init__(self,segments):self.segments=segments
    def iter_segments(self):return iter(self.segments)

class TargetBoundaryTests(unittest.TestCase):
    def test_psram_bulk_profile_accepts_4096_only_after_declared_negotiation(self):
        d=Mock();d._wireless_text_reads=True;d._wireless_bulk_size=4096;d.read_memory.side_effect=lambda a,n:bytes(n)
        self.assertEqual(len(read_flash_range(d,FLASH,8192)),8192)
        self.assertEqual([c.args for c in d.read_memory.call_args_list],[(FLASH,4096),(FLASH+4096,4096)])
    def test_recovery_verification_never_reprograms_and_resets_only_after_all_checks(self):
        import hashlib
        d=Mock();d._bridge._mux=None;target={'uid':'same'};payload=bytes(END-APP);original=bytes(END-FLASH)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'app').write_bytes(payload);(p/'original').write_bytes(original)
            with patch('target_ops.identity',return_value=target),patch('target_ops.verify_image',return_value={'verified':True,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}),patch('target_ops.read_flash_range',return_value=original[:APP-FLASH]):
                result=verify_programmed_application(d,p/'app',hashlib.sha256(payload).hexdigest(),p/'original',target)
        self.assertTrue(result['readback_only']);self.assertFalse(result['programmed']);d.reset.assert_called_once()
        d._flash.load_flm.assert_not_called();d._flash.burn_bin.assert_not_called();d.write_memory.assert_not_called()
    def test_recovery_mismatch_cannot_reset_or_program(self):
        import hashlib
        d=Mock();payload=bytes(END-APP)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'app').write_bytes(payload);(p/'original').write_bytes(bytes(END-FLASH))
            with patch('target_ops.identity',return_value={'uid':'same'}),patch('target_ops.verify_image',side_effect=RuntimeError('mismatch')):
                with self.assertRaisesRegex(RuntimeError,'mismatch'):
                    verify_programmed_application(d,p/'app',hashlib.sha256(payload).hexdigest(),p/'original',{'uid':'same'})
        d.reset.assert_not_called();d._flash.burn_bin.assert_not_called()
    def test_recovery_wrong_image_hash_cannot_reach_hardware(self):
        d=Mock()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'app').write_bytes(bytes(END-APP));(p/'original').write_bytes(bytes(END-FLASH))
            with self.assertRaises(ValueError):verify_programmed_application(d,p/'app','0'*64,p/'original',{})
        self.assertEqual(d.mock_calls,[])
    def test_ram_write_cannot_touch_flash_or_system(self):
        for address in [FLASH,APP,0x40023c14,0xe000ed0c,RAM_END-1]:
            with self.assertRaises(ValueError):checked_range(address,4,write=True)
    def test_reads_are_bounded_and_never_include_peripherals(self):
        for address,size in [(RAM,4097),(True,4),(RAM_END-2,4),(0x40000000,4)]:
            with self.assertRaises(ValueError):checked_range(address,size)
        checked_range(RAM,4096);checked_range(END-4,4)
    def test_flash_snapshot_uses_public_read_bounds(self):
        d=Mock();d.read_memory.side_effect=lambda a,n:bytes(n)
        self.assertEqual(len(read_flash_range(d,FLASH,49152)),49152)
        self.assertTrue(all(c.args[1]<=4096 for c in d.read_memory.call_args_list))
    def test_declared_text_bulk_mode_bounds_each_native_read_to_1024(self):
        d=Mock();d._wireless_text_reads=True;d.read_memory.side_effect=lambda a,n:bytes(n)
        self.assertEqual(len(read_flash_range(d,FLASH,8192)),8192)
        self.assertEqual([c.args for c in d.read_memory.call_args_list],[(FLASH+i,1024) for i in range(0,8192,1024)])
    def test_incomplete_native_bulk_read_stops_without_replay(self):
        d=Mock();d._wireless_text_reads=True;d.read_memory.return_value=b'bad'
        with self.assertRaises(RuntimeError):read_flash_range(d,FLASH,4096)
        self.assertEqual(d.read_memory.call_count,1)
    def test_failed_image_stage_cannot_load_algorithm_or_program_target(self):
        d=Mock();d._wireless_text_reads=True;link=Mock()
        before={'uid':'expected'}
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);image=p/'image.bin';image.write_bytes(bytes(END-APP));flm=p/'algorithm.flm';flm.write_bytes(b'FLM')
            import hashlib
            digest=hashlib.sha256(image.read_bytes()).hexdigest()
            link.upload_file.side_effect=['/WLINK/A.FLM',TimeoutError('Image commit acknowledgement lost')]
            with patch('target_ops.identity',return_value=before),patch('target_ops.read_flash_range',return_value=bytes(APP-FLASH)),patch('target_ops.native_f411_algorithm',return_value=Mock()),patch('mklink.cmsis_dap.algorithm_catalog.extract_algorithm',return_value=flm):
                with self.assertRaises(TimeoutError):flash_application(d,link,image,digest,folder,expected_uid='expected')
        self.assertEqual(link.upload_file.call_count,2)
        d._flash.load_flm.assert_not_called();d._flash.burn_bin.assert_not_called();d.reset.assert_not_called()
    def test_tail_and_external_data_are_preserved(self):
        original=bytes([0xa5])*524288;app=struct.pack('<II',RAM_END-8,APP+9)+b'new app'
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'backup').write_bytes(original);(p/'test.axf').write_bytes(b'elf')
            with patch('elftools.elf.elffile.ELFFile',return_value=Elf([Segment(APP,app),Segment(0x90000000,b'external')])):
                result=prepare_internal_image(p/'test.axf',p/'backup',p/'image.bin')
            image=(p/'image.bin').read_bytes();self.assertEqual(image[:len(app)],app);self.assertEqual(image[len(app):],original[APP-FLASH+len(app):]);self.assertEqual(result['excluded_external_segments'],[{'address':0x90000000,'bytes':8}])
    def test_bootloader_segment_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'backup').write_bytes(bytes(524288));(p/'test.axf').write_bytes(b'elf')
            with patch('elftools.elf.elffile.ELFFile',return_value=Elf([Segment(FLASH,b'bad')])):
                with self.assertRaises(ValueError):prepare_internal_image(p/'test.axf',p/'backup',p/'image.bin')
            self.assertFalse((p/'image.bin').exists())
    def test_changed_or_partial_flash_image_cannot_reach_hardware(self):
        d=Mock();link=Mock()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'bad.bin';p.write_bytes(b'changed')
            with self.assertRaises(ValueError):flash_application(d,link,p,'0'*64,folder,expected_uid='expected')
        self.assertEqual(d.mock_calls,[]);self.assertEqual(link.mock_calls,[])
    def test_oversized_rtt_downlink_rejected_before_start(self):
        d=Mock()
        with self.assertRaises(ValueError):capture_rtt(d,RAM,[2],1,input_text='x'*257)
        self.assertEqual(d.mock_calls,[])
    def test_bad_rtt_address_channel_and_duration(self):
        d=Mock()
        for address,channels,duration in [(RAM+1,[2],1),(RAM,[8],1),(RAM,[2,2],1),(RAM,[2],31)]:
            with self.assertRaises(ValueError):capture_rtt(d,address,channels,duration)
        self.assertEqual(d.mock_calls,[])

if __name__=='__main__':unittest.main()
