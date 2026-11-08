"""Publication guard regressions; synthetic secret strings never leave memory."""
import importlib.util,unittest,io,tempfile,urllib.error
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_audit',ROOT/'tools/check-public.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
spec=importlib.util.spec_from_file_location('prepare_upstream',ROOT/'tools/prepare-upstream.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)
class PublicationTests(unittest.TestCase):
    def test_recursive_sources_include_component_and_frontend(self):
        files=audit.selected()
        self.assertIn('desktop/mklink-wireless-config/src/App.tsx',files)
        self.assertIn('boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/components/probe_protocol/probe_protocol.c',files)
        self.assertNotIn('desktop/mklink-wireless-config/src-tauri/src/bin/node-update-check.rs',files)
        for name in ('http_reply_stubs.h','test_http_diagnostics.c','test_http_reply.c','test_mux_recovery.c'):
            self.assertIn('tests/'+name,files)
    def test_synthetic_key_is_detected_without_value_in_report(self):
        secret='gh'+'p_'+'A'*36
        report=audit.audit(['README.md'],lambda _:secret.encode())
        self.assertFalse(report['ok']);self.assertEqual(report['findings'][0]['rule'],'github-token')
        self.assertNotIn(secret,str(report))
    def test_private_and_binary_paths_rejected(self):
        for name in ('runs/secret.json','backups/flash.bin','desktop/mklink-wireless-config/output/setup.exe'):
            self.assertFalse(audit.audit([name],lambda _:b'private')['ok'])
    def test_harmless_text_passes(self):
        self.assertTrue(audit.audit(['README.md'],lambda _:b'Mklink Remote')['ok'])
    def test_private_markers_stay_outside_source_and_report(self):
        marker='private-'+'fixture-marker'
        report=audit.audit(['README.md'],lambda _:marker.encode(),[marker])
        self.assertFalse(report['ok']);self.assertEqual(report['findings'][0]['rule'],'private-marker')
        self.assertNotIn(marker,str(report))
class DownloadTests(unittest.TestCase):
    def test_gateway_retry_replaces_partial(self):
        error=urllib.error.HTTPError(prepare.SDK_URL,504,'gateway timeout',None,None)
        with tempfile.TemporaryDirectory() as directory, patch.object(prepare.urllib.request,'urlopen',side_effect=[error,io.BytesIO(b'verified input')]) as request, patch.object(prepare.time,'sleep') as sleep:
            partial=Path(directory)/'sdk.partial';partial.write_bytes(b'incomplete download')
            prepare.download_sdk(partial)
            self.assertEqual(partial.read_bytes(),b'verified input');self.assertEqual(request.call_count,2);sleep.assert_called_once_with(1)
    def test_transient_failure_has_bounded_retries(self):
        with patch.object(prepare.urllib.request,'urlopen',side_effect=TimeoutError()) as request, patch.object(prepare.time,'sleep') as sleep:
            with self.assertRaises(TimeoutError):prepare.download_sdk(Path('unused.partial'))
            self.assertEqual(request.call_count,4);self.assertEqual(sleep.call_count,3)
    def test_permanent_error_is_not_retried(self):
        error=urllib.error.HTTPError(prepare.SDK_URL,404,'not found',None,None)
        with patch.object(prepare.urllib.request,'urlopen',side_effect=error) as request, patch.object(prepare.time,'sleep') as sleep:
            with self.assertRaises(urllib.error.HTTPError):prepare.download_sdk(Path('unused.partial'))
            request.assert_called_once();sleep.assert_not_called()
if __name__=='__main__':unittest.main()
