"""Run with PYTHONPATH pointing at the staged Remote server. No hardware."""
import unittest
from unittest.mock import MagicMock, patch

from mklink import dump_benchmark
from mklink.mux_watch import MuxWatchSession, PackedWatchSample


class TailTests(unittest.TestCase):
    def test_bulk_stop_drains_more_than_queue_budget_before_ack(self):
        import struct
        from mklink.mux import MuxTransport, packet
        from mklink.mux_bulk_watch import MuxBulkWatchSession, HEADER
        mux = MuxTransport(lambda wire: len(wire))
        mux.capabilities = mux.BULK_WATCH_CAPABILITY
        watch = MuxBulkWatchSession(mux, [(0x20000000,4096)], .1)
        watch.stream_id, watch._started = 1, True
        sample = event_id = 0
        collected = []
        def receive(deadline=None):
            nonlocal sample,event_id
            for _ in range(10):
                sample += 1
                for offset in range(0,4096,200):
                    n=min(200,4096-offset);event_id+=1
                    flags=int(offset==0) | (2 if offset+n==4096 else 0)
                    body=HEADER.pack(1,sample,sample*100000,sample*100000+100,7,7,4096,offset,n,0,flags)+bytes(n)
                    mux.feed(packet(0x42,mux.epoch,event_id,body))
            if sample==100:
                mux.feed(packet(0xB5,mux.epoch,mux._pending[1],b'\0'+struct.pack('<I',1)))
        with patch.object(mux,'_wait',receive):
            watch.stop(on_tail=collected.extend)
        self.assertEqual(len(collected),100)
        self.assertGreater(100*4096,mux.WATCH_QUEUE_BYTES)
        self.assertEqual(mux.dropped_bytes,{})
        self.assertFalse(watch._started)
        self.assertFalse(watch._pending)

    def test_tail_decode_failure_poisoned_pending_stop_without_replay(self):
        from mklink.mux import MuxTransport
        writes=[];mux=MuxTransport(writes.append)
        with patch.object(mux,'_wait'), self.assertRaisesRegex(ValueError,'bad tail'):
            mux.request(0x31,on_wait=lambda: (_ for _ in ()).throw(ValueError('bad tail')))
        self.assertIsNotNone(mux._error)
        self.assertEqual(len(writes),1)
        with self.assertRaises(ConnectionError):mux.request(0x31)
        self.assertEqual(len(writes),1)

    def test_client_cancellation_waits_for_submitted_stop_cleanup(self):
        cancelled=False;acknowledged=False
        session=MagicMock();session.stats={}
        session.read_frames.return_value=[PackedWatchSample(t,b'',0) for t in (0,200000,300000)]
        def stop(*,on_watch_tail):
            nonlocal cancelled,acknowledged
            cancelled=True
            on_watch_tail([PackedWatchSample(400000,b'',0)])
            acknowledged=True
        session.stop.side_effect=stop
        with patch('mklink.dump_memory.DumpMemoryStreamSession',return_value=session), patch.object(dump_benchmark.time,'monotonic',side_effect=[0,0,0,.51]):
            with self.assertRaises(InterruptedError):
                dump_benchmark.measure(MagicMock(),[(0x20000000,4)],duration=.5,period=.1,cancelled=lambda:cancelled)
        self.assertTrue(acknowledged)
        session.stop.assert_called_once()

    def test_window_excludes_warmup_and_samples_at_or_after_end(self):
        session = MagicMock()
        def samples(*times):
            return [PackedWatchSample(t, b'', 0) for t in times]
        session.read_frames.return_value = samples(0, 100000, 200000, 300000)
        session.stop.side_effect = lambda *, on_watch_tail: on_watch_tail(samples(400000, 500000, 600000))
        session.stats = {}
        with patch('mklink.dump_memory.DumpMemoryStreamSession', return_value=session), \
                patch.object(dump_benchmark.time, 'monotonic', side_effect=[0, 0, 0, .51]):
            result = dump_benchmark.measure(MagicMock(), [(0x20000000, 4)], duration=.5, period=.1)
        self.assertEqual(result['samples_before_stop'], 2)
        self.assertEqual(result['tail_samples_in_window'], 1)
        self.assertEqual(result['tail_samples_after_window'], 2)
        self.assertEqual(result['samples'], 3)
        self.assertEqual(result['sample_hz'], 10)
        session.stop.assert_called_once()

    def test_failed_stop_never_claims_queued_data(self):
        watch = MuxWatchSession(MagicMock(), [(0x20000000, 4)], .1)
        watch.transport.request.side_effect = ConnectionError('STOP unconfirmed')
        with patch.object(watch, 'read_frames') as read:
            with self.assertRaises(ConnectionError):
                watch.stop(drain_tail=True, packed=True)
        read.assert_not_called()
        watch.transport.request.assert_called_once_with(0x31)

    def test_late_batch_arrives_before_stop(self):
        session = MagicMock()
        session.read_frames.return_value = [PackedWatchSample(t, b'', 0)
                                            for t in (0, 200000, 300000, 400000, 500000, 600000)]
        session.stats = {}
        with patch('mklink.dump_memory.DumpMemoryStreamSession', return_value=session), \
                patch.object(dump_benchmark.time, 'monotonic', side_effect=[0, 0, 0, .51]):
            result = dump_benchmark.measure(MagicMock(), [(0x20000000, 4)], duration=.5, period=.1)
        self.assertEqual(result['samples'], 3)
        self.assertEqual(result['prestop_samples_after_window'], 2)


if __name__ == '__main__':
    unittest.main()
