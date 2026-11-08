"""Portable offline software checks. Does not open a serial/BLE/target device."""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];APP=ROOT/'desktop/mklink-wireless-config'
def main():
    p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--runtime',type=Path,default=ROOT/'.deps/remote-staged');p.add_argument('--skip-rust',action='store_true');p.add_argument('--report',type=Path,default=ROOT/'output/source-verification.json');args=p.parse_args()
    sdk=args.sdk.resolve();assert (sdk/'mklink/device.py').is_file(),'Provide the verified extracted SDK directory'
    runtime=args.runtime.resolve()
    pin=json.loads((APP/'adapter/upstream.json').read_text())
    provenance=json.loads((runtime/'remote-provenance.json').read_text())
    assert provenance['upstream_commit']==pin['upstream_commit'],'Stage the pinned Remote backend before verification'
    for name, hashes in pin['files'].items():
        assert hashlib.sha256((runtime/name).read_bytes()).hexdigest()==hashes['server_sha256'],f'Staged backend changed: {name}'
    adapter=APP/'adapter/mklink_remote'
    current={'mklink_remote/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in adapter.glob('*.py')}
    assert current==provenance['adapter_sha256'],'Restage the current Remote adapter before verification'
    for name,digest in current.items():
        assert hashlib.sha256((runtime/name).read_bytes()).hexdigest()==digest,f'Staged adapter changed: {name}'
    env=dict(os.environ,PYTHONPATH=str(runtime),TAURI_CONFIG=json.dumps({'bundle':{'resources':[]}}))
    # Source tests intentionally omit binary bundle resources; release packaging
    # must prepare and validate real resources using docs/BUILD.md.
    npm='npm.cmd' if os.name=='nt' else 'npm'
    steps=[('publication audit',[sys.executable,str(ROOT/'tools/check-public.py')],ROOT),
           ('publication guard tests',[sys.executable,'-m','unittest','discover','-s','tests','-p','test_publication.py','-v'],ROOT),
           ('frontend tests',[npm,'test'],APP),('frontend build',[npm,'run','build'],APP),
           ('installer and BLE tests',[sys.executable,'-m','unittest','discover','-s','tools','-p','test_*.py','-v'],APP),
           ('target boundary tests',[sys.executable,'-m','unittest','discover','-s','tests/wireless-system','-p','test_*.py','-v'],ROOT),
           ('staged backend regressions',[sys.executable,'-m','unittest','discover','-s','tests','-p','run_staged_*.py','-v'],ROOT)]
    if os.name=='nt':
        for name in ('http_reply','http_receive','mux_recovery'):
            steps.append((name+' boundary tests',[sys.executable,str(ROOT/'tests'/('run_'+name+'.py'))],ROOT))
    if not args.skip_rust:
        steps.append(('Rust tests',['cargo','test','--locked','--manifest-path','src-tauri/Cargo.toml'],APP))
        steps.append(('desktop source build',['cargo','build','--locked','--bins','--features','tauri/custom-protocol','--manifest-path','src-tauri/Cargo.toml'],APP))
    results=[];args.report.parent.mkdir(parents=True,exist_ok=True)
    for name,command,cwd in steps:
        began=time.monotonic();r=subprocess.run(command,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace')
        log=args.report.parent/(name.replace(' ','-')+'.log');log.write_text(r.stdout,encoding='utf8')
        results.append(dict(name=name,ok=r.returncode==0,exit_code=r.returncode,seconds=round(time.monotonic()-began,2)))
        print(name, 'PASS' if r.returncode==0 else 'FAIL',flush=True)
    report=dict(ok=all(r['ok'] for r in results),scope='offline source checks; no hardware; bundle resources excluded',results=results)
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    return 0 if report['ok'] else 1
if __name__=='__main__':sys.exit(main())
