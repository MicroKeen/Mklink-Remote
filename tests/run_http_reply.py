"""Compile the real HTTP sender with host doubles; never touches hardware."""
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
main = root / 'boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/main'
out = root / 'tmp/http-reply-test'
out.mkdir(parents=True, exist_ok=True)
headers = ['esp_http_server.h', 'esp_heap_caps.h', 'esp_timer.h', 'freertos/FreeRTOS.h',
           'freertos/idf_additions.h', 'freertos/queue.h', 'freertos/task.h', 'lwip/sockets.h']
for header in headers:
    path = out / header
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#include "http_reply_stubs.h"\n')
exe = out / 'http-reply.exe'
subprocess.run([os.environ.get('CC', 'gcc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                f'-I{out}', f'-I{root / "tests"}', f'-I{main}',
                str(root / 'tests/test_http_reply.c'), '-o', str(exe)], check=True)
subprocess.run([str(exe)], check=True, timeout=15)
