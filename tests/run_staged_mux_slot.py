"""Run with PYTHONPATH set to a freshly staged Remote server."""
import struct
import unittest
from unittest.mock import patch

from mklink.mux import MuxTransport, packet


class SlotTest(unittest.TestCase):
    def test_waiting_stop_precedes_next_overdue_heartbeat(self):
        writes = []
        mux = MuxTransport(writes.append)
        mux.epoch = 7
        mux.ready = True
        with patch('mklink.mux.time.monotonic') as now:
            now.return_value = mux._last_command + 1.1
            mux.tick()

            def receive_then_tick():
                # Exercise the reader winning the condition lock before the waiting STOP.
                self.assertLess(len(writes), 3, 'A second heartbeat overtook STOP')
                op, req, _, _ = mux._pending
                now.return_value += 1.2
                mux.feed(packet(op | 0x80, mux.epoch, req, b'\0'))
                mux.tick()

            with patch.object(mux, '_wait', receive_then_tick):
                self.assertEqual(mux.request(0x31), b'')
            mux.tick()
        self.assertEqual([struct.unpack_from('<B', wire, 5)[0] for wire in writes],
                         [0x02, 0x31, 0x02])


if __name__ == '__main__':
    unittest.main()
