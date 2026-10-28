"""Create the board-specific offline firmware bundle from a successful IDF build."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

root = Path(__file__).resolve().parents[3]
app = root / "desktop/mklink-wireless-config"
build = root / "boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/build"
version = json.loads((build / "project_description.json").read_text(encoding="utf-8"))["project_version"]
dest = app / "src-tauri/resources/firmware"
dest.mkdir(parents=True, exist_ok=True)
sources = [(0, "bootloader.bin", build / "bootloader/bootloader.bin"),
           (0x8000, "partition-table.bin", build / "partition_table/partition-table.bin"),
           (0x9000, "nvs-init.bin", None),
           (0x10000, "n16r8_wireless_gateway.bin", build / "n16r8_wireless_gateway.bin"),
           (0x410000,"ota_data_initial.bin",build/"ota_data_initial.bin")]
images = []
for address, name, source in sources:
    target = dest / name
    if source:
        shutil.copyfile(source, target)
    else:
        target.write_bytes(b"\xff" * 0x6000)
    data = target.read_bytes()
    images.append(dict(address=address, file=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
manifest = dict(project="n16r8_wireless_gateway", version=version, target="esp32s3",
                board="third-party-esp32-s3-n16r8", flash_bytes=16777216,
                flash_mode="dio", flash_freq="40m",ota_protocol=1,psram_required_bytes=8388608,images=images)
(dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(dest / "flash_args").write_text("--flash_mode dio --flash_freq 40m --flash_size 16MB\n" +
                                "\n".join(f"{a:#x} {n}" for a,n,_ in sources) + "\n", encoding="utf-8")
(dest / "README.txt").write_text(
    f"Mklink ESP32-S3 N16R8 default firmware {version}\n"
    "For the third-party 16MB Flash / 8MB PSRAM board only. Official board images are separate.\n"
    "USB1: UART0 115200 configuration/logging. USB2: V4 guarded CDC command host + MSC file staging.\nAP/STA/AP+STA, encrypted BLE configuration, embedded mobile Web, BOOT GPIO0, WS2812B GPIO48.\nUSB pairing reports the per-device random AP password and management token.\n"
    "Preferred installation: desktop app > Install default firmware > Backup and install.\n"
    "Every install verifies a full 16MB backup before writing. This package resets NVS/network configuration.\n"
    "APP OTA via WiFi or BLE uses PSRAM staging and inactive4MiB slots with boot confirmation and rollback.\n"
    "OTA APP upload preserves NVS; the default USB installation resets NVS and OTA selection.\n"
    "Keep the original backup. Do not install on encrypted or secure-boot devices.\n"
    "Advanced esptool users: back up first, then from this folder run:\n"
    "python -m esptool --chip esp32s3 -p <PORT> -b 460800 write-flash @flash_args\n"
    "Images are checked by SHA256 in manifest.json. USB enumeration is implemented;\n"
    "V4 requires valid FS descriptors, an identity echo and a complete version reply. Native binary streams are exclusive, generation-bound and never replayed after an uncertain result.\n"
    "The desktop supports bounded STM32F411 SRAM access, preserved internal APP programming and RTT through the native MKLink SDK. Central remote target-business sessions remain unavailable.\n",
    encoding="utf-8")
out = app / "output/releases"
out.mkdir(parents=True, exist_ok=True)
archive = out / f"mklink-n16r8-default-{version}.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(dest.iterdir()):
        z.write(f, f.name)
print(archive)
