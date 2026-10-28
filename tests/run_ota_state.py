"""Compile actual OTA state machine with host platform doubles; no hardware."""
import os,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
main=root/'boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/main'
json=Path(os.environ['IDF_PATH'])/'components/json/cJSON'
headers=['esp_err.h','esp_app_desc.h','esp_app_format.h','esp_heap_caps.h','esp_ota_ops.h','esp_partition.h','esp_system.h','esp_timer.h','nvs.h','freertos/FreeRTOS.h','freertos/semphr.h','freertos/task.h','mbedtls/base64.h','mbedtls/sha256.h']
with tempfile.TemporaryDirectory(prefix='mklink-ota-state-') as folder:
    tmp=Path(folder)
    for header in headers:
        p=tmp/header;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('#include "ota_state_stubs.h"\n')
    exe=tmp/'ota-state.exe'
    subprocess.run([os.environ.get('CC','gcc'),'-std=c11','-Wall','-Wextra','-Werror',f'-I{tmp}',f'-I{root/"tests"}',f'-I{main}',f'-I{json}',str(root/'tests/test_ota_state.c'),str(json/'cJSON.c'),'-lm','-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
