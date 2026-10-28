"""Publication guard regressions; synthetic secret strings never leave memory."""
import importlib.util,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_audit',ROOT/'tools/check-public.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
class PublicationTests(unittest.TestCase):
    def test_recursive_sources_include_component_and_frontend(self):
        files=audit.selected()
        self.assertIn('desktop/mklink-wireless-config/src/App.tsx',files)
        self.assertIn('boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/components/probe_protocol/probe_protocol.c',files)
        self.assertNotIn('desktop/mklink-wireless-config/src-tauri/src/bin/node-update-check.rs',files)
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
if __name__=='__main__':unittest.main()
