"""Portable offline software checks. Does not open a serial/BLE/target device."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];APP=ROOT/'desktop/mklink-wireless-config'
def main():
    p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--skip-rust',action='store_true');p.add_argument('--report',type=Path,default=ROOT/'output/source-verification.json');args=p.parse_args()
    sdk=args.sdk.resolve();assert (sdk/'mklink/device.py').is_file(),'Provide the verified extracted SDK directory'
    env=dict(os.environ,PYTHONPATH=str(sdk),TAURI_CONFIG=json.dumps({'bundle':{'resources':[]}}))
    # Source tests intentionally omit binary bundle resources; release packaging
    # must prepare and validate real resources using docs/BUILD.md.
    npm='npm.cmd' if os.name=='nt' else 'npm'
    steps=[('publication audit',[sys.executable,str(ROOT/'tools/check-public.py')],ROOT),
           ('publication guard tests',[sys.executable,'-m','unittest','discover','-s','tests','-p','test_publication.py','-v'],ROOT),
           ('frontend tests',[npm,'test'],APP),('frontend build',[npm,'run','build'],APP),
           ('installer and BLE tests',[sys.executable,'-m','unittest','discover','-s','tools','-p','test_*.py','-v'],APP),
           ('target boundary tests',[sys.executable,'-m','unittest','discover','-s','tests/wireless-system','-p','test_*.py','-v'],ROOT)]
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
