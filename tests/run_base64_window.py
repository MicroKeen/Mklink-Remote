"""Compile pinned vendor base64 implementation unchanged, with minimal config."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
vendor=Path(os.environ['IDF_PATH'])/'components/mbedtls/mbedtls'
with tempfile.TemporaryDirectory(prefix='mklink-base64-') as folder:
    tmp=Path(folder);(tmp/'minimal.h').write_text('#define MBEDTLS_BASE64_C\n#define MBEDTLS_PLATFORM_C\n')
    exe=tmp/'base64-window.exe'
    subprocess.run([os.environ.get('CC','gcc'),'-std=c11','-Wall','-Wextra','-Werror',
        '-DMBEDTLS_CONFIG_FILE="minimal.h"',f'-I{tmp}',f'-I{vendor/"include"}',f'-I{vendor/"library"}',
        str(root/'tests/test_base64_window.c'),str(vendor/'library/base64.c'),str(vendor/'library/constant_time.c'),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
