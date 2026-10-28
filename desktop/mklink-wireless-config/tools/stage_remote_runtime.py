"""Stage a pinned, product-private server without editing an MKLink checkout.

Original client modules remain byte-identical. Adaptation sources and patch live
in Mklink Remote; no runtime monkeypatching, global installation or PR required.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

def main():
    app=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    pin=json.loads((app/'adapter/upstream.json').read_text())
    dest=args.destination.resolve()
    if dest.exists(): raise RuntimeError('Use a new staging directory; existing artifacts preserved')
    blob=subprocess.check_output(['git','-c','core.autocrlf=false','-C',str(args.source),'archive',pin['upstream_commit'],
                                  'Mklink-AI-Probe/mklink','Mklink-AI-Probe/gui/dist','Mklink-AI-Probe/pyproject.toml'])
    dest.mkdir(parents=True)
    license_text=subprocess.check_output(['git','-C',str(args.source),'show',pin['upstream_commit']+':LICENSE'])
    (dest/'LICENSE-MKLINK').write_bytes(license_text)
    with tarfile.open(fileobj=io.BytesIO(blob)) as archive:
        for member in archive.getmembers():
            parts=Path(member.name).parts[1:]
            target=dest.joinpath(*parts).resolve()
            if not target.is_relative_to(dest) or not member.isfile(): continue
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    for name,entry in pin['files'].items():
        if hashlib.sha256((dest/name).read_bytes()).hexdigest()!=entry['base_sha256']:
            raise RuntimeError('Upstream mismatch: '+name)
    subprocess.run(['git','-c','core.autocrlf=false','apply','--unsafe-paths','--directory',str(dest),str(app/'adapter/server-compat.patch')],cwd=dest.anchor,check=True)
    shutil.copytree(app/'adapter/mklink_remote',dest/'mklink_remote',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name,entry in pin['files'].items():
        if hashlib.sha256((dest/name).read_bytes()).hexdigest()!=entry['server_sha256']:
            raise RuntimeError('Server adapter mismatch: '+name)
    clients={}
    for name in ['remote/mcp.py','remote/sites.py','remote/client.py','mcp_server.py']:
        p=dest/'mklink'/name
        if not p.exists(): continue
        original=subprocess.check_output(['git','-C',str(args.source),'show',pin['upstream_commit']+':Mklink-AI-Probe/mklink/'+name])
        if p.read_bytes()!=original: raise RuntimeError('Original client modified: '+name)
        clients[name]=hashlib.sha256(original).hexdigest()
    (dest/'remote-provenance.json').write_text(json.dumps(dict(pin,original_client_sha256=clients,adapter_sha256={str(p.relative_to(dest)).replace(chr(92),'/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in (dest/'mklink_remote').glob('*.py')}),indent=2)+'\n')
    print(json.dumps({'ok':True,'destination':str(dest),'original_client_sha256':clients}))

if __name__=='__main__':main()
