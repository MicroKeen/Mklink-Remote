"""Run with PYTHONPATH pointing at the staged Remote server. No hardware."""
import unittest
from unittest.mock import MagicMock, patch

from mklink import dump_benchmark
from mklink.mux_watch import MuxWatchSession, PackedWatchSample


class TailTests(unittest.TestCase):
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
