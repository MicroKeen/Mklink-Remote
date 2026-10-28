"""Private server entry. Original MCP is deliberately not bundled as an entry."""
import os
from pathlib import Path
import sys

def main():
    default=Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'MklinkRemote/backend'
    os.environ.setdefault('MKLINK_RUNTIME_DIR',str(default))
    if len(sys.argv)>1 and sys.argv[1]=='runtime':
        from mklink.cli import main as runtime_main
        return runtime_main()
    if len(sys.argv)>1 and sys.argv[1]=='s3-workbench':
        from mklink_remote.s3_workbench import main as workbench_main
        return workbench_main()
    raise SystemExit('Private server: use mklink-remote CLI; use original MKLink remote MCP for skills')

if __name__=='__main__':main()
