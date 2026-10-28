"""Fetch immutable public build inputs, isolated from installed MKLink clients.

Never installs a skill, edits an MCP, or executes downloaded build code.
"""
import argparse,hashlib,json,shutil,subprocess,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SDK_SHA='555710fff446f80776b3fab418343d1370b6a083faa38f7d568896ac63c3d300'
SDK_URL='https://github.com/MicroKeen/Mklink-AI-Probe/releases/download/v0.4.0/Mklink-AI-Probe-v0.4.0-Skill.zip'
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,default=ROOT/'.deps');parser.add_argument('--source',type=Path);parser.add_argument('--sdk-archive',type=Path);parser.add_argument('--sdk-only',action='store_true');args=parser.parse_args()
    dest=args.directory.resolve();dest.mkdir(parents=True,exist_ok=True)
    archive=args.sdk_archive or dest/'mklink-sdk-0.4.0.zip'
    if not archive.exists():
        partial=archive.with_suffix('.partial')
        with urllib.request.urlopen(SDK_URL,timeout=90) as response,partial.open('wb') as out:shutil.copyfileobj(response,out)
        if hashlib.sha256(partial.read_bytes()).hexdigest()!=SDK_SHA:raise RuntimeError('SDK download digest mismatch; retained .partial for inspection')
        partial.rename(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=SDK_SHA:raise RuntimeError('SDK archive digest mismatch')
    sdk=dest/'sdk-0.4.0'
    marker=sdk/'.archive-sha256'
    if sdk.exists() and (not marker.is_file() or marker.read_text()!=SDK_SHA):raise RuntimeError('Existing SDK directory not verified; use a fresh dependency directory')
    if not sdk.exists():
        with zipfile.ZipFile(archive) as z:
            candidates=[n for n in z.namelist() if n.endswith('/pyproject.toml') and n.count('/')<=2]
            if 'pyproject.toml' in z.namelist():candidates=['pyproject.toml']
            if len(candidates)!=1:raise RuntimeError('Ambiguous SDK archive root')
            prefix=candidates[0][:-len('pyproject.toml')]
            for info in z.infolist():
                if info.is_dir() or not info.filename.startswith(prefix):continue
                relative=info.filename[len(prefix):];target=(sdk/relative).resolve()
                if not target.is_relative_to(sdk):raise RuntimeError('Unsafe SDK archive path')
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(info))
        marker.write_text(SDK_SHA)
    result={'sdk':str(sdk),'sdk_archive_sha256':SDK_SHA}
    if not args.sdk_only:
        pin=json.loads((ROOT/'desktop/mklink-wireless-config/adapter/upstream.json').read_text())['upstream_commit']
        source=args.source or dest/'upstream'
        if not source.exists():
            subprocess.run(['git','init',str(source)],check=True)
            subprocess.run(['git','-C',str(source),'remote','add','origin','https://github.com/MicroKeen/Mklink-AI-Probe.git'],check=True)
            subprocess.run(['git','-C',str(source),'fetch','--depth=1','origin',pin],check=True)
        resolved=subprocess.check_output(['git','-C',str(source),'rev-parse',pin+'^{commit}'],text=True).strip()
        if resolved!=pin:raise RuntimeError('Unexpected upstream source commit')
        result.update(source=str(source.resolve()),upstream_commit=pin)
    (dest/'build-inputs.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result))
if __name__=='__main__':main()
