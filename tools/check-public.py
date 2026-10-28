"""Audit the explicit publication set, index, or a commit; never print secret values.

This is a project-specific leak guard, not a claim that regex detects every secret.
Review new files and third-party provenance in addition to running it.
"""
import argparse,fnmatch,hashlib,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RULES=json.loads((ROOT/'tools/public-files.json').read_text(encoding='utf8'))
PATTERNS={
    'private-key':r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'github-token':r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b',
    'aws-key':r'\bAKIA[A-Z0-9]{16}\b',
    'credential-url':r'https?://[^\s/]+:[^\s/@]+@',
    'personal-home':r'(?i)(?:[A-Z]:[/\\]+Users[/\\]+[\w.-]+|/Users/[\w.-]+)',
    'private-project':r'(?i)(?:[A-Z]:[/\\]+Projects[/\\]+[^/\\\s"\x27]+|[A-Z]:[/\\]+Tools[/\\]+MKLink|[A-Z]:[/\\]+Espressif)',
    'physical-address':r'(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b',
}
def allowed(name):return any(fnmatch.fnmatchcase(name,p) for p in RULES['include']) and not any(fnmatch.fnmatchcase(name,p) for p in RULES['exclude'])
def selected():
    return sorted({p.relative_to(ROOT).as_posix() for glob in RULES['include'] for p in ROOT.glob(glob+'/*' if glob.endswith('/**') else glob) if p.is_file() and allowed(p.relative_to(ROOT).as_posix())})
def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args])
def audit(files,read,private_markers=()):
    findings=[];total=0
    for name in files:
        if not allowed(name):findings.append({'file':name,'rule':'outside-public-manifest'});continue
        data=read(name);total+=len(data)
        if len(data)>10*1024*1024:findings.append({'file':name,'rule':'oversize-source-file'})
        if Path(name).suffix.lower() in {'.exe','.dll','.bin','.zip','.axf','.elf','.pdb','.pack','.pdf'}:findings.append({'file':name,'rule':'binary-distribution-or-private-artifact'})
        if b'\0' in data[:8192]:continue
        try:text=data.decode('utf8')
        except UnicodeDecodeError:continue
        for line_no,line in enumerate(text.splitlines(),1):
            for marker in private_markers:
                if marker and marker.casefold() in line.casefold():findings.append({'file':name,'line':line_no,'rule':'private-marker'})
            for rule,pattern in PATTERNS.items():
                # Exact invalid-URL unit fixture is intentionally public. Other
                # values on the same line still undergo every check.
                candidate=line.replace('http://a:b@192.168.1.1','') if rule=='credential-url' else line
                if rule=='physical-address':candidate=candidate.replace('02:00:00:12:34:56','')  # locally administered demo identity
                if re.search(pattern,candidate):findings.append({'file':name,'line':line_no,'rule':rule})
    digest=hashlib.sha256('\n'.join(f'{name}\0{hashlib.sha256(read(name)).hexdigest()}' for name in files).encode()).hexdigest()
    return dict(ok=not findings,files=len(files),bytes=total,content_sha256=digest,findings=findings)
def main():
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group();group.add_argument('--index',action='store_true');group.add_argument('--ref');parser.add_argument('--paths',type=Path);parser.add_argument('--report',type=Path);parser.add_argument('--private-markers',type=Path,help='Local-only JSON array of identifiers; never publish this file');args=parser.parse_args()
    if args.index:
        files=git('ls-files','-z').decode().rstrip('\0').split('\0');read=lambda n:git('show',':'+n)
    elif args.ref:
        files=git('ls-tree','-r','--name-only','-z',args.ref).decode().rstrip('\0').split('\0');read=lambda n:git('show',args.ref+':'+n)
    else:files=selected();read=lambda n:(ROOT/n).read_bytes()
    files=sorted(n for n in files if n);markers=json.loads(args.private_markers.read_text(encoding='utf8')) if args.private_markers else []
    report=audit(files,read,markers)
    if args.paths:
        args.paths.parent.mkdir(parents=True,exist_ok=True);args.paths.write_bytes(b'\0'.join(n.encode() for n in files)+b'\0')
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2));return 0 if report['ok'] else 1
if __name__=='__main__':sys.exit(main())
