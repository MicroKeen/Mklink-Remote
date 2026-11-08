import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'desktop/mklink-wireless-config/tools'))
from advanced_ops import capture_watch,capture_trace,stop_trace_recorder
class AdvancedCaptureBounds(unittest.TestCase):
    def test_watch_reports_stopping_before_ack_and_never_claims_ack_on_failure(self):
        for fail in (False,True):
            device=Mock();device._bridge.supports_multiplex.return_value=True
            session=Mock();session.stats={};order=[]
            def stopped(**kwargs):
                order.append('ack')
                if fail:raise RuntimeError('STOP failed')
            session.stop.side_effect=stopped
            with tempfile.TemporaryDirectory() as folder,patch('mklink.dump_memory.DumpMemoryStreamSession',return_value=session),patch('advanced_ops.time.monotonic',return_value=0):
                args=dict(root=folder,stop=Mock(is_set=lambda:True),progress=lambda phase,*_:order.append(phase))
                if fail:
                    with self.assertRaisesRegex(RuntimeError,'STOP failed'):capture_watch(device,0x20000000,4,.1,.05,**args)
                else:
                    result=capture_watch(device,0x20000000,4,.1,.05,**args)
                    self.assertTrue(result['mux_stop_verified'])
                    self.assertIsNone(result['received_samples_s'])
                self.assertEqual(order[:2],['stopping','ack'])

    def test_native_rtt_startup_tail_and_recorder_stop_are_preserved(self):
        import threading
        from types import SimpleNamespace
        from mklink.mux_rtt import MuxRTTSession
        class Transport:
            FAST_TRANSFER_BYTES=128
            transfer_quantum=64
            def __init__(self):
                self._commands=threading.RLock();self._condition=threading.Condition()
                self._rtt_manager=None;self.dropped_bytes={};self.calls=[]
            def _check(self):pass
            def request(self,kind,data=b''):
                self.calls.append((kind,data))
                if kind==0x20:
                    self._rtt_manager.publish(b'\x01\0\x01\0\0\0final-stop')
                    return bytes([2,0])
                if kind==0x21:return bytes([len(data)-1])
                return b''
        transport=Transport()
        session=MuxRTTSession(transport,{'down_buffers':[]},1,[1])
        session.start('0x20019db0')
        self.assertEqual(session.read_channels(0),{1:b'final-stop'})
        self.assertEqual(session.read_channels(0),{1:b''})
        session.manager.recorders.add(1)
        view=SimpleNamespace(_session=session)
        stop_trace_recorder(view)
        self.assertTrue(session._running)
        self.assertTrue(view._tasklist_requested)
        stop_trace_recorder(view)
        session.stop()
        self.assertEqual([data for op,data in transport.calls if op==0x21],[b'\x01\x02'])
        self.assertEqual(transport.calls[-1][0],0x22)

    def test_recorder_stop_cannot_interrupt_another_consumer(self):
        import threading
        session=Mock();rtt=session._session
        rtt._channel=1;rtt.transport._commands=threading.RLock()
        rtt.manager.consumers={rtt:(2,2),object():(2,0)}
        with self.assertRaisesRegex(RuntimeError,'shared with another'):
            stop_trace_recorder(session)
        rtt.send_input.assert_not_called()

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
