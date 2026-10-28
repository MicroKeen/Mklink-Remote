import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'adapter'))
from mklink_remote.s3_workbench import Workbench
class DiagnosticsTest(unittest.TestCase):
 def test_incremental_partial_and_rotation(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);p=root/'runtime.log';p.write_bytes(b'INFO ready\n')
   w=Workbench();w.client=object();w.info={'probe_id':'s3-012345abcdef'}
   with patch('mklink.runtime.runtime_dir',return_value=root):
    get=lambda:w.dispatch({'method':'diagnostics'})['lines']
    self.assertEqual(get(),['INFO ready']);self.assertEqual(get(),[])
    with p.open('ab') as f:f.write(b'WARN partial')
    self.assertEqual(get(),[])
    with p.open('ab') as f:f.write(b' done\n')
    self.assertEqual(get(),['WARN partial done']);self.assertEqual(get(),[])
    p.write_bytes(b'ERROR x\n');self.assertEqual(get(),['ERROR x'])
if __name__=='__main__':unittest.main()
