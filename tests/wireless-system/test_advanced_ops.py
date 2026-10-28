import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'desktop/mklink-wireless-config/tools'))
from advanced_ops import capture_watch,capture_trace,retained_rtt_tail
class AdvancedCaptureBounds(unittest.TestCase):
    def test_native_rtt_startup_tail_is_retained_for_trace_handoff(self):
        import threading
        from types import SimpleNamespace
        from mklink.mux_rtt import MuxRTTSession
        class Transport:
            def __init__(self):self._commands=threading.RLock();self.frames=[]
            def request(self,kind,*args):
                if kind==0x20:self.frames.append(b'\x40\0\x01\0\0\0final-stop')
                return b''
            def drain(self,kind,channel=None):
                result=self.frames[:];self.frames.clear();return result
        transport=Transport();original=transport.drain
        session=MuxRTTSession(transport,{'down_buffers':[]},1,[1])
        device=SimpleNamespace(_bridge=SimpleNamespace(enable_multiplex=lambda:transport),
            rtt_start=lambda **kw:session.start(kw['addr']),rtt_stop=session.stop)
        with retained_rtt_tail(device,0x20019db0):
            self.assertEqual(session.read_channels(0),{1:b'final-stop'})
            self.assertEqual(session.read_channels(0),{1:b''})
        self.assertEqual(transport.drain,original)
    def test_invalid_watch_region_rate_or_duration_never_starts_native_device(self):
        for address,size,duration,period in [(0x08000000,36,1,.05),(0x20000001,36,1,.05),(0x2001fffc,8,1,.05),(0x20000000,4096,1,.05),(0x20000000,36,31,.05),(0x20000000,36,1,0),(0x20000000,36,1,float('nan'))]:
            device=Mock()
            with self.assertRaises(ValueError):capture_watch(device,address,size,duration,period,root='unused')
            self.assertFalse(device.mock_calls)
    def test_legacy_probe_is_rejected_without_host_memory_polling(self):
        device=Mock();device._bridge.supports_multiplex.return_value=False
        with self.assertRaisesRegex(RuntimeError,'no memory polling fallback'):capture_watch(device,0x20000000,36,1,.05,root='unused')
        device.read_memory.assert_not_called();device._bridge.enable_multiplex.assert_not_called()
    def test_trace_failure_stops_native_session_without_task_name_guessing(self):
        device=Mock();device.systemview_start.return_value={};device.systemview_read.side_effect=RuntimeError('capture error')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,'capture error'):capture_trace(device,0x20019db0,1,root=folder)
        device.systemview_stop.assert_called_once();device.systemview_resolve_task_names.assert_not_called()
    def test_trace_invalid_address_never_starts(self):
        device=Mock()
        with self.assertRaises(ValueError):capture_trace(device,0x90000000,5,root='unused')
        self.assertFalse(device.mock_calls)
if __name__=='__main__':unittest.main()
