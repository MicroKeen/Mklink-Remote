"""Create a fresh public-only tree for validation. Never delete or overwrite."""
import argparse,importlib.util,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('destination',type=Path);args=p.parse_args();dest=args.destination.resolve()
    if dest.exists():raise SystemExit('Use a new destination; existing files preserved')
    spec=importlib.util.spec_from_file_location('public_audit',ROOT/'tools/check-public.py');audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
    files=audit.selected();report=audit.audit(files,lambda n:(ROOT/n).read_bytes())
    if not report['ok']:raise SystemExit(json.dumps(report))
    for name in files:
        target=dest/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
    print(json.dumps({'ok':True,'files':len(files),'content_sha256':report['content_sha256']}))
if __name__=='__main__':main()
