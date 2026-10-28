"""Finite B1 lifecycle guards; SDK assembler remains the integrity authority."""
import hashlib,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'desktop/mklink-wireless-config/tools'))
from native_bulk import read_flash_binary,finite_parser,performance_sweep

class BinaryReadTests(unittest.TestCase):
    def test_invalid_region_never_contacts_probe(self):
        for address,size in [(0x20000000,4096),(0x08000001,4096),(0x08000000,4095),(0x08000000,524289),(0x0807fffc,4096)]:
            device=Mock()
            with self.assertRaises(ValueError):read_flash_binary(device,address,size)
            self.assertFalse(device.mock_calls)

    def scenario(self,*,bad_block=False,crc_errors=0):
        data=bytes(range(256))*16
        frames=[dict(format='B1',timestamp_us=100,flags=0,total_size=4096,
                     block_size=2048,block_index=i,block_count=2,block_crc_ok=not bad_block,
                     regions=[(0,data[i*2048:(i+1)*2048])]) for i in range(2)]
        session=Mock();session._mux_watch=None;session.parser.crc_errors=crc_errors
        session.read_frames.return_value=frames
        session.stats=dict(parser_crc_errors=crc_errors,parser_dropped_frames=0,parser_dropped_bytes=0,firmware_flagged_frames=0)
        link=Mock();link.usb_metrics_supported=True;link.read_max=32768
        link.call.side_effect=[dict(rx_pending=0),dict(tx_start_us=100,last_rx_us=20100,rx_bytes=4200)]
        device=SimpleNamespace(_bridge=Mock(link=link))
        return data,session,device

    def test_exact_payload_and_producer_time_exclude_radio_cleanup(self):
        data,session,device=self.scenario()
        with patch('mklink.dump_memory.DumpMemoryStreamSession',return_value=session):
            actual,report=read_flash_binary(device,0x08000000,len(data))
        self.assertEqual(actual,data);self.assertEqual(report['sha256'],hashlib.sha256(data).hexdigest())
        self.assertEqual(report['usb_producer_payload_bytes_s'],204800)
        session.start.assert_called_once();session.stop.assert_called_once()
        self.assertEqual(device._bridge.link.call.call_count,2)

    def test_bad_crc_is_not_replayed_and_native_stop_still_runs(self):
        for kwargs in [dict(bad_block=True),dict(crc_errors=1)]:
            _,session,device=self.scenario(**kwargs)
            with patch('mklink.dump_memory.DumpMemoryStreamSession',return_value=session):
                with self.assertRaises((RuntimeError,ValueError)):read_flash_binary(device,0x08000000,4096)
            session.start.assert_called_once();session.stop.assert_called_once()
            self.assertEqual(device._bridge.link.call.call_count,2 if kwargs.get('crc_errors') else 1)

    def test_only_exact_command_echo_can_precede_native_magic(self):
        command=b'cmd.dump_memory(0x08000000, 4096, 0)'
        for prefix in [b'garbage',command+b'\n\r\n>>> corrupted']:
            parser=finite_parser([4096],command)
            with self.assertRaisesRegex(RuntimeError,'Unrecognized'):parser.feed(prefix+b'MPMDMPMD')
        parser=finite_parser([4096],command)
        parser.feed(command[:4]);parser.feed(command[4:]+b'\n\r\n>>> MPMDMPMD')
        self.assertEqual(parser.command_echo_bytes,len(command)+7)
        self.assertEqual(parser.dropped_bytes,0)

    def test_previous_tail_blocks_new_dump(self):
        _,session,device=self.scenario();device._bridge.link.call.side_effect=[dict(rx_pending=64)]
        with patch('mklink.dump_memory.DumpMemoryStreamSession',return_value=session):
            with self.assertRaisesRegex(RuntimeError,'undrained'):read_flash_binary(device,0x08000000,4096)
        session.start.assert_not_called()

    def test_clock_matrix_uses_usb_producer_and_restores_default_after_corruption(self):
        device=Mock();link=SimpleNamespace(poisoned=False)
        baseline=bytes(524288)
        with patch('native_bulk.read_flash_binary',side_effect=[(baseline,{}),RuntimeError('CRC mismatch')]) as read:
            with self.assertRaisesRegex(RuntimeError,'CRC mismatch'):
                performance_sweep(device,link,repetitions=3)
        self.assertEqual(read.call_count,2)
        self.assertEqual(device._flash.set_swd_clock.call_args.args,(1000000,))

    def test_invalid_repetition_count_never_contacts_target(self):
        for count in [0,6,True,1.5]:
            device=Mock()
            with self.assertRaises(ValueError):performance_sweep(device,Mock(),repetitions=count)
            self.assertFalse(device.mock_calls)

if __name__=='__main__':unittest.main()
