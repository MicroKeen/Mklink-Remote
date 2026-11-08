"""The isolated helper uses the same adapter as the shared backend, without IO."""
import sys, unittest, json, tempfile
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'desktop/mklink-wireless-config/tools'))
import mklink_wireless
import build_remote_server
from mklink import transport_factory

class NativeDeviceTests(unittest.TestCase):
    def test_owned_connection_and_cleanup_use_shared_adapter(self):
        link=Mock(node_id='020000123456',read_max=4096,native_binary_bulk=False)
        bridge=Mock();device=Mock();device._bridge=bridge
        original=transport_factory.create_bridge
        def connect():
            self.assertIs(transport_factory.create_bridge('s3-020000123456'),bridge)
            with self.assertRaises(ConnectionError):transport_factory.create_bridge('COM1')
        device._connect.side_effect=connect
        with patch.object(mklink_wireless,'Device',return_value=device), patch.object(mklink_wireless,'WirelessBridge',return_value=bridge):
            with mklink_wireless.native_device(link,project_root='unused') as actual:
                self.assertIs(actual,device)
                self.assertIs(transport_factory.create_bridge,original)
            device.close.assert_called_once();bridge.close.assert_called_once()
        link.acquire.assert_not_called()

    def test_failed_connect_still_closes_adapter(self):
        device=Mock();device._connect.side_effect=RuntimeError('connect failed')
        bridge=Mock();link=Mock(node_id='020000123456')
        with patch.object(mklink_wireless,'Device',return_value=device), patch.object(mklink_wireless,'WirelessBridge',return_value=bridge):
            with self.assertRaisesRegex(RuntimeError,'connect failed'):
                with mklink_wireless.native_device(link,project_root='unused'):self.fail('unexpected connection')
        bridge.close.assert_called_once()

class RuntimeBuildPinTests(unittest.TestCase):
    def test_server_rejects_stale_commit_or_patch_before_freezing(self):
        pin=json.loads((Path(build_remote_server.__file__).resolve().parents[1]/'adapter/upstream.json').read_text())
        for field in ('upstream_commit','files'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);manifest=dict(pin);manifest[field]='stale' if field=='upstream_commit' else {}
                (root/'remote-provenance.json').write_text(json.dumps(manifest))
                argv=['build','--staged',folder,'--assets',folder,'--output',str(root/'out'),'--stage-only']
                with patch.object(sys,'argv',argv), patch.object(build_remote_server.subprocess,'run') as freeze:
                    with self.assertRaisesRegex(RuntimeError,'currently pinned'):
                        build_remote_server.main()
                    freeze.assert_not_called()
