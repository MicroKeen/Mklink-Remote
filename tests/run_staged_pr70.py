"""PR #70 integration in the staged Remote backend; no hardware IO."""
import struct
import unittest
from unittest.mock import Mock, patch

from mklink import transport_factory
from mklink.mux import MuxTransport, packet
from mklink.mux_watch import MuxWatchSession
from mklink.mux_bulk_watch import MuxBulkWatchSession, HEADER
from mklink_remote.s3_transport import WirelessBridge, WirelessLink


class IntegrationTests(unittest.TestCase):
    def test_remote_backpressure_is_explicit_and_does_not_change_requested_rate(self):
        from mklink.dump_memory import DumpMemoryStreamSession
        from mklink.mux_watch import PackedWatchSample
        for kind,raises in [('s3',True),('serial',False)]:
            bridge=Mock(transport_kind=kind);session=DumpMemoryStreamSession(bridge,[(0x20000000,4)],.00125)
            session.started=True;session._mux_watch=Mock()
            session._mux_watch.read_frames.side_effect=[[PackedWatchSample(1000000,b'',0)],[PackedWatchSample(1100000,b'',0)]]
            with patch('time.monotonic',side_effect=[10,16]):
                session.read_frames()
                if raises:
                    with self.assertRaisesRegex(RuntimeError,'reduce sampling rate'):session.read_frames()
                else:session.read_frames()
            self.assertEqual(session.period,.00125)
            session._mux_watch.stop.assert_not_called()

    def test_remote_backpressure_allows_recovered_stall_but_bounds_persistent_lag(self):
        from mklink.dump_memory import DumpMemoryStreamSession
        from mklink.mux_watch import PackedWatchSample
        for timestamp,raises in [(6100000,False),(3100000,True)]:
            session=DumpMemoryStreamSession(Mock(transport_kind='s3'),[(0x20000000,4)],.00125)
            session.started=True;session._mux_watch=Mock()
            session._mux_watch.read_frames.side_effect=[[PackedWatchSample(t,b'',0)] for t in (1000000,1100000,timestamp)]
            with patch('time.monotonic',side_effect=[10,13,15.1]):
                session.read_frames();session.read_frames()
                if raises:
                    with self.assertRaisesRegex(RuntimeError,'reduce sampling rate'):session.read_frames()
                else:
                    session.read_frames();self.assertIsNone(session._delivery_behind_since)

    def test_remote_reset_boundary_reanchors_delivery_clock(self):
        from mklink.dump_memory import DumpMemoryStreamSession
        from mklink.mux_watch import PackedWatchSample
        session=DumpMemoryStreamSession(Mock(transport_kind='s3'),[(0x20000000,4)],.00125)
        session.started=True;session._mux_watch=Mock()
        session._mux_watch.read_frames.side_effect=[[PackedWatchSample(1000000,b'',0)],[PackedWatchSample(100,b'',0,2)]]
        with patch('time.monotonic',side_effect=[10,20]):
            session.read_frames();session.read_frames()
        self.assertEqual(session._delivery_lag,0)

    def test_core_factory_selects_remote_extensions(self):
        node = dict(node_id='020000123456', transport='http',
                    address='http://127.0.0.1', token='test')
        sentinel = object()
        with patch('mklink_remote.s3_registry.load_nodes', return_value={'s3-020000123456':node}),              patch.object(WirelessBridge, 'from_node', return_value=sentinel) as create:
            self.assertIs(transport_factory.create_bridge('s3-020000123456'), sentinel)
            create.assert_called_once_with(node)
        with patch('mklink_remote.s3_registry.load_nodes', return_value={}):
            with self.assertRaisesRegex(ConnectionError, 'no USB fallback'):
                transport_factory.create_bridge('s3-020000123456')

    def test_wireless_uses_upstream_policy_and_keeps_file_hooks(self):
        from mklink_remote.s3_registry import public_node
        self.assertFalse(public_node('s3-020000123456',
                         {'node_id':'020000123456','transport':'http'})['local_usb'])
        bridge = WirelessBridge(WirelessLink(Mock(), '020000123456'))
        self.assertEqual(bridge.command_timeout_floor, 60)
        self.assertEqual(bridge.transport_kind, 's3')
        self.assertFalse(bridge.allow_algorithm_fallback)
        self.assertTrue(bridge.require_reader_exit)
        self.assertEqual(transport_factory.file_transfer_hook(bridge, 'prepare_firmware'),
                         bridge.prepare_firmware)
        bridge.link.poisoned = True
        self.assertFalse(bridge.transport_healthy)

    def test_http_background_ping_does_not_complete_pending_stop(self):
        writes = []
        mux = MuxTransport(writes.append, command_timeout=60, background_heartbeats=True)
        mux.ready, mux.epoch = True, 7
        now = mux._last_command
        with patch('mklink.mux.time.monotonic', return_value=now):
            mux._send(0x31, b'')
        pending = mux._pending
        with patch('mklink.mux.time.monotonic', return_value=now+5):
            mux.tick()
        self.assertEqual([wire[5] for wire in writes], [0x31, 2])
        mux.feed(packet(0x82, 7, 2, b'\0'))
        self.assertEqual(mux._pending, pending)
        self.assertIsNone(mux._reply)
        mux.feed(packet(0xB1, 7, 1, b'\0'))
        self.assertIsNone(mux._pending)
        self.assertFalse(mux._heartbeats)

    def test_narrow_tail_decodes_before_resetting_negotiated_width(self):
        mux = MuxTransport(Mock())
        watch = MuxWatchSession(mux, [(0x20000000, 1)], .001)
        watch._narrow_batch = True
        body = bytes([0,9,2,1])+struct.pack('<IBIB',1000,7,2000,8)
        mux.feed(packet(0x41, mux.epoch, 1, body))
        mux.request = Mock(return_value=b'')
        tail = watch.stop(drain_tail=True, packed=True)
        self.assertEqual([s.timestamp_us for s in tail], [1000,2000])
        self.assertEqual(watch.samples,2)
        self.assertFalse(watch._narrow_batch)
        mux.request.assert_called_once_with(0x31)

    def test_bulk_tail_preserves_complete_sample_and_acquisition_metadata(self):
        mux = MuxTransport(Mock())
        mux.capabilities = mux.BULK_WATCH_CAPABILITY
        watch = MuxBulkWatchSession(mux, [(0x20000000,2048)], .1)
        watch.stream_id, watch._started = 1, True
        for seq,offset in enumerate(range(0,2048,200),1):
            n=min(200,2048-offset)
            flags=int(offset==0) | (2 if offset+n==2048 else 0)
            body=HEADER.pack(1,1,100,110,7,7,2048,offset,n,0,flags)+bytes(n)
            mux.feed(packet(0x42,mux.epoch,seq,body))
        mux.request=Mock(return_value=struct.pack('<I',1))
        tail=watch.stop(drain_tail=True)
        self.assertEqual(len(tail),1)
        self.assertEqual(tail[0]['regions'],[(0,bytes(2048))])
        self.assertEqual(tail[0]['acquisition']['end_us'],110)
        self.assertFalse(tail[0]['acquisition']['atomic_snapshot'])
        self.assertEqual(mux.drain(0x42,255),[])

    def test_invalid_bulk_stop_ack_does_not_drain(self):
        mux=MuxTransport(Mock());watch=MuxBulkWatchSession(mux,[(0x20000000,2048)],.1)
        watch.stream_id,watch._started=1,True
        mux.request=Mock(return_value=struct.pack('<I',2))
        with patch.object(watch,'read_frames') as read:
            with self.assertRaisesRegex(Exception,'STOP acknowledgement'):
                watch.stop(drain_tail=True)
        read.assert_not_called()

    def test_old_watch_capabilities_fail_before_start(self):
        mux=MuxTransport(Mock());mux.capabilities=8
        with patch.object(mux,'request') as request:
            with self.assertRaisesRegex(RuntimeError,'0x618'):
                MuxWatchSession(mux,[(0x20000000,4)],.001).start()
        request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
