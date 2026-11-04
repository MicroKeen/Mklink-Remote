"""Run with PYTHONPATH set to the staged Remote backend."""
import struct
import unittest
from unittest.mock import patch

from mklink.mux import MuxTransport, packet
from mklink.mux_watch import MuxWatchSession


class WatchDeadlineTest(unittest.TestCase):
    def setUp(self):
        self.mux = MuxTransport(lambda _: None)
        self.watch = MuxWatchSession(self.mux, [(0xE000E018, 4)], .00125)

    def feed(self, seq, status, timestamp, data=b''):
        self.mux.feed(packet(0x41, self.mux.epoch, seq,
                             struct.pack('<BBI', 0, status, timestamp) + data))

    @patch('mklink.mux_watch.time.monotonic')
    def test_deadline_sees_valid_sample_already_queued(self, now):
        now.return_value = 10
        self.feed(1, 5, 1000)
        self.assertEqual(self.watch.read_frames(), [])
        self.feed(2, 5, 2250)
        self.feed(3, 0, 3500, b'abcd')
        now.return_value = 13.1
        frames = self.watch.read_frames(max_bytes=6)
        self.assertEqual(frames[0]['regions'], [(0, b'abcd')])
        self.assertEqual((self.watch.samples, self.watch.read_errors, self.watch.gaps), (1, 2, 2))

    @patch('mklink.mux_watch.time.monotonic')
    def test_silence_after_one_error_has_no_measured_device_duration(self, now):
        now.return_value = 10
        self.feed(1, 5, 1000)
        self.watch.read_frames()
        now.return_value = 13
        with self.assertRaisesRegex(RuntimeError, 'delivery gap.*1 reported error.*0 device us.*0xE000E018'):
            self.watch.read_frames()

    @patch('mklink.mux_watch.time.monotonic')
    def test_errors_covering_deadline_across_device_clock_wrap(self, now):
        now.return_value = 0
        self.feed(1, 5, 0xfffffff0)
        self.watch.read_frames()
        now.return_value = 3.1
        self.feed(2, 5, (0xfffffff0 + 3050000) & 0xffffffff)
        with self.assertRaisesRegex(RuntimeError, 'failed continuously.*2 reported error.*3050000 device us'):
            self.watch.read_frames()


if __name__ == '__main__':
    unittest.main()
