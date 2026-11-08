"""Select redistributable algorithm bytes from verified, licensed CMSIS packs."""
import argparse,hashlib,json,shutil,zipfile
from pathlib import Path

def digest(data):return hashlib.sha256(data).hexdigest()
def inside(root,name):
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('Asset path escapes root')
    return path

def prepare(source,destination):
    if destination.exists():raise ValueError('Use a new asset directory')
    assets=source/'mklink';packs=json.loads((assets/'builtin_packs/manifest.json').read_text(encoding='utf8'))
    flm=json.loads((assets/'builtin_flm/manifest.json').read_text(encoding='utf8'));licensed={}
    for entry in packs['packs']:
        if entry.get('redistribution_basis') not in ('Apache-2.0','BSD-3-Clause','Apache-2.0 AND BSD-3-Clause') or not entry.get('licenses'):
            raise ValueError('Pack has no reviewed redistribution basis')
        path=inside(assets/'builtin_packs',entry['file'])
        if digest(path.read_bytes())!=entry['sha256']:raise ValueError('Pack checksum mismatch')
        with zipfile.ZipFile(path) as archive:
            for notice in entry['licenses']:
                if digest(archive.read(notice['path']))!=notice['sha256']:raise ValueError('Pack license checksum mismatch')
            for name in archive.namelist():
                if name.lower().endswith('.flm'):licensed.setdefault(digest(archive.read(name)),[]).append(entry['pack_id'])
    targets=[];used=set()
    for target in flm['targets']:
        algorithms=target['algorithms']
        if not algorithms or not all(a['sha256'] in licensed for a in algorithms):continue
        target=dict(target);option=target.get('option_algorithm')
        if option and option['sha256'] not in licensed:target['option_algorithm']=None
        used.update(a['sha256'] for a in algorithms)
        if target.get('option_algorithm'):used.add(option['sha256'])
        targets.append(target)
    blobs=[b for b in flm['blobs'] if b['sha256'] in used]
    if {b['sha256'] for b in blobs}!=used:raise ValueError('Missing referenced algorithm')
    for blob in blobs:
        data=inside(assets/'builtin_flm',blob['file']).read_bytes()
        if digest(data)!=blob['sha256'] or len(data)!=blob['size']:raise ValueError('Algorithm checksum mismatch')
    destination.mkdir(parents=True)
    shutil.copy2(source/'pyproject.toml',destination/'pyproject.toml')
    pack_dest=destination/'mklink/builtin_packs';pack_dest.mkdir(parents=True)
    shutil.copy2(assets/'builtin_packs/manifest.json',pack_dest/'manifest.json')
    for entry in packs['packs']:
        target=inside(pack_dest,entry['file']);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(inside(assets/'builtin_packs',entry['file']),target)
    dest=destination/'mklink/builtin_flm';dest.mkdir(parents=True)
    for blob in blobs:
        path=inside(dest,blob['file']);path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(inside(assets/'builtin_flm',blob['file']),path)
    flm.update(targets=targets,blobs=blobs,target_count=len(targets),blob_count=len(blobs),release_note='Only algorithms byte-matched to bundled licensed packs')
    (dest/'manifest.json').write_text(json.dumps(flm,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    report={'algorithm_blobs':len(blobs),'targets':len(targets),'packs':len(packs['packs']),'algorithm_pack_sources':{h:licensed[h] for h in sorted(used)}}
    (destination/'redistribution.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--destination',type=Path,required=True);a=p.parse_args()
    r=prepare(a.sdk,a.destination);print(json.dumps({k:v for k,v in r.items() if k!='algorithm_pack_sources'}))
