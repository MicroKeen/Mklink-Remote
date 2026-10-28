"""Freeze the product-private server; never build or replace the user's MCP."""
import argparse,json,os,subprocess,sys,shutil
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--staged',required=True,type=Path);p.add_argument('--assets',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--stage-only',action='store_true');args=p.parse_args()
    source=args.staged.resolve();assets=args.assets.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    provenance=json.loads((source/'remote-provenance.json').read_text())
    import hashlib
    for name,item in provenance['files'].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest()!=item['server_sha256']:raise RuntimeError('Staged server changed: '+name)
    for name,digest in provenance.get('adapter_sha256',{}).items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Private adapter changed: '+name)
    for name,digest in provenance['original_client_sha256'].items():
        if hashlib.sha256((source/'mklink'/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Original client changed: '+name)
    for name in ['builtin_flm','builtin_packs']:
        if not (assets/name/'manifest.json').is_file():raise RuntimeError('Missing verified algorithm/Pack assets')
    entry=out/'remote_server_entry.py';entry.write_text('from mklink_remote.__main__ import main\nmain()\n',encoding='utf8')
    env=dict(os.environ,PYTHONPATH=str(source),TEMP=str(out),TMP=str(out))
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--name','mklink-remote-server',
             '--distpath',str(out/'dist'),'--workpath',str(out/'work'),'--specpath',str(out),'-p',str(source)]
    for module in ['mklink','mklink_remote','elftools','pyocd','cmsis_pack_manager','hid','bleak','cryptography']:
        command+=['--collect-all',module]
    command+=['--copy-metadata','mklink','--copy-metadata','pyocd',
              '--add-data',str(source/'LICENSE-MKLINK')+os.pathsep+'.',
              '--add-data',str(source/'gui/dist')+os.pathsep+'gui/dist',
              '--add-data',str(source/'remote-provenance.json')+os.pathsep+'.']
    for name in ['builtin_flm','builtin_packs']:
        command+=['--add-data',str(assets/name)+os.pathsep+'mklink/'+name]
    command+=[str(entry)]
    subprocess.run(command,cwd=source,env=env,check=True)
    app=Path(__file__).resolve().parents[1]
    destination=app/'src-tauri/resources/device-tool/remote-server'
    if not args.stage_only:shutil.copytree(out/'dist/mklink-remote-server',destination,dirs_exist_ok=True)
    print('REMOTE_SERVER_FROZEN — original MCP remains external')

if __name__=='__main__':main()
