import importlib.util,json,tempfile,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('release_assets',ROOT/'desktop/mklink-wireless-config/tools/prepare-release-assets.py')
assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)
class ReleaseAssetsTests(unittest.TestCase):
    def fixture(self,root):
        sdk=root/'sdk';flm=sdk/'mklink/builtin_flm';packs=sdk/'mklink/builtin_packs'
        flm.mkdir(parents=True);packs.mkdir(parents=True);(sdk/'pyproject.toml').write_text('version = "0.4.0"')
        with zipfile.ZipFile(packs/'safe.pack','w') as z:z.writestr('LICENSE',b'Apache-2.0 fixture');z.writestr('Flash/safe.FLM',b'algorithm')
        entry={'file':'safe.pack','pack_id':'fixture.safe','sha256':assets.digest((packs/'safe.pack').read_bytes()),'licenses':[{'path':'LICENSE','sha256':assets.digest(b'Apache-2.0 fixture')}],'redistribution_basis':'Apache-2.0'}
        (packs/'manifest.json').write_text(json.dumps({'schema':1,'packs':[entry]}))
        known=assets.digest(b'algorithm');unknown=assets.digest(b'unknown')
        (flm/'safe.flm').write_bytes(b'algorithm');(flm/'unknown.flm').write_bytes(b'unknown')
        (flm/'manifest.json').write_text(json.dumps({'schema':1,'blobs':[{'file':'safe.flm','sha256':known,'size':9},{'file':'unknown.flm','sha256':unknown,'size':7}],'targets':[{'part_number':'safe','algorithms':[{'sha256':known,'blob':'safe.flm'}],'option_algorithm':{'sha256':unknown,'blob':'unknown.flm'}},{'part_number':'unknown','algorithms':[{'sha256':unknown,'blob':'unknown.flm'}]}]}))
        return sdk
    def test_only_matched_algorithms_and_notices_are_distributed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);sdk=self.fixture(root);out=root/'release';(sdk/'mklink/builtin_packs/unreviewed.pack').write_bytes(b'unreviewed');r=assets.prepare(sdk,out)
            self.assertFalse((out/'mklink/builtin_packs/unreviewed.pack').exists())
            self.assertEqual(r['algorithm_blobs'],1);self.assertEqual(r['targets'],1)
            manifest=json.loads((out/'mklink/builtin_flm/manifest.json').read_text())
            self.assertIsNone(manifest['targets'][0]['option_algorithm']);self.assertFalse((out/'mklink/builtin_flm/unknown.flm').exists())
            self.assertEqual((out/'mklink/builtin_packs/safe.pack').read_bytes(),(sdk/'mklink/builtin_packs/safe.pack').read_bytes())
            with self.assertRaises(ValueError):assets.prepare(sdk,out)
    def test_modified_pack_fails_before_output_creation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);sdk=self.fixture(root);(sdk/'mklink/builtin_packs/safe.pack').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'checksum'):assets.prepare(sdk,root/'release')
            self.assertFalse((root/'release').exists())
    def test_asset_path_cannot_escape(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):assets.inside(Path(d),'../escape')
