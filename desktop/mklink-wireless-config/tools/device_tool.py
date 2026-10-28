"""Bundled installer: verified full backup precedes every default firmware write.

Runs standalone after PyInstaller packaging. The firmware manifest selects only
the supported N16R8 image set; this tool never changes eFuse or uses force.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

import esptool
from esptool import cmds
import serial
from win_serial_transport import install_for_esptool

install_for_esptool()

TOTAL = 16 * 1024 * 1024
CHUNK = 65536


def emit(stage, detail, **extra):
    print("@TOOL " + json.dumps(dict(stage=stage, detail=detail, **extra), ensure_ascii=False), flush=True)


def read_segment(esp, address, size):
    if type(address) is not int or type(size) is not int or not 0<=address<address+size<=TOTAL or size>CHUNK:
        raise ValueError("Invalid bounded backup region")
    # Prove blank regions with the device digest instead of transporting many
    # megabytes of 0xff over UART. The resulting full-size backup is still
    # independently compared with the whole chip MD5 before any write.
    expected=esp.flash_md5sum(address,size).lower()
    erased=b'\xff'*size
    if hashlib.md5(erased).hexdigest()==expected:return erased
    # Keep framing/window/checksum in the upstream esptool implementation.
    data=esp.read_flash(address,size)
    if len(data)!=size or hashlib.md5(data).hexdigest()!=expected:
        raise RuntimeError("备份分段长度或板端摘要不一致")
    return data


def load_images(manifest_path):
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("project") != "n16r8_wireless_gateway" or manifest.get("target") != "esp32s3" or manifest.get("flash_bytes") != TOTAL:
        raise ValueError("默认固件包型号不匹配")
    images, end = [], 0
    for image in sorted(manifest["images"], key=lambda i: i["address"]):
        path = (manifest_path.parent / image["file"]).resolve()
        if not path.is_relative_to(manifest_path.parent) or not path.is_file():
            raise ValueError("固件文件路径无效")
        data = path.read_bytes()
        if len(data) != image["bytes"] or hashlib.sha256(data).hexdigest() != image["sha256"]:
            raise ValueError("默认固件校验失败，请重新安装上位机")
        address = image["address"]
        if address < end or address + len(data) > TOTAL:
            raise ValueError("固件写入范围无效")
        end = address + len(data)
        images.append((address, data))
    expected={0,0x8000,0x9000,0x10000}
    if manifest.get('ota_protocol')==1:expected.add(0x410000)
    if {a for a, _ in images} != expected:
        raise ValueError("默认固件镜像集合不完整")
    if manifest.get('ota_protocol')==1 and dict(images)[0x410000]!=b'\xff'*8192:
        raise ValueError("OTA 初始选择区必须为空白")
    return manifest, images


def connect(port, expected_mac=None, baud=460800):
    esp = esptool.detect_chip(port, baud=115200, connect_attempts=3)
    try:
        mac = ":".join(f"{b:02x}" for b in esp.read_mac())
        if esp.CHIP_NAME != "ESP32-S3" or (expected_mac and mac != expected_mac):
            raise RuntimeError("板卡身份改变，已停止安装")
        if esp.get_secure_boot_enabled() or esp.get_flash_encryption_enabled():
            raise RuntimeError("设备已启用安全启动或 Flash 加密，不强制安装")
        esp = esp.run_stub()
        if hasattr(esp._port, "set_buffer_size"):
            esp._port.set_buffer_size(rx_size=1048576, tx_size=65536)
        cmds.attach_flash(esp)
        if (esp.flash_id() >> 16) & 255 != 24:
            raise RuntimeError("本固件只支持 16MB Flash 的 ESP32-S3 N16R8")
        esp.change_baud(baud)
        esp.flash_set_parameters(TOTAL)
        return esp, mac
    except BaseException:
        esp._port.close()
        raise


def verify_boot(port):
    device = serial.Serial(port=None, baudrate=115200, timeout=0.1)
    device.dtr = False
    device.rts = False
    device.port = port
    request_id = str(uuid.uuid4())
    deadline = time.monotonic() + 12
    with device:
        device.rts = True
        time.sleep(0.1)
        device.rts = False
        sent = False
        while time.monotonic() < deadline:
            line = device.readline().decode("utf-8", errors="replace").strip()
            if ("CONFIG_READY" in line or "HOST_READY" in line) and not sent:
                request = dict(v=1, id=request_id, method="get_status", params={})
                device.write(("@MKCFG " + json.dumps(request) + "\n").encode())
                sent = True
            if line.startswith("@MKCFG "):
                try:
                    reply = json.loads(line[7:])
                    if reply.get("id") == request_id and reply.get("ok") is True:
                        return reply["data"]["device"]["id"]
                except (ValueError, KeyError, TypeError):
                    pass
        raise RuntimeError("写入已校验，但启动配置接口未响应；请保留备份并检查 USB1 日志，不自动重写")


def install(port, manifest_path, backup_dir):
    manifest, images = load_images(manifest_path)
    emit("connecting", "检查 ESP32-S3、Flash 与安全状态")
    esp, mac = connect(port)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"{mac.replace(':', '')}-{stamp}-{uuid.uuid4().hex[:6]}.bin"
    journal = dict(mac=mac, port=port, firmware=manifest["version"], backup=str(backup), backup_complete=False, flash_started=False, flash_complete=False, verified=False,backup_method='device_digest_proven_blank_segments_and_native_esptool_reads_plus_whole_chip_md5',read_failures=0)
    journal_path = backup.with_suffix(".json")
    def save():
        journal_path.write_text(json.dumps(journal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    save()
    start = 0
    try:
        for attempt in range(10):
            try:
                if start:
                    prefix = backup.read_bytes()
                    if len(prefix) != start or hashlib.md5(prefix).hexdigest() != esp.flash_md5sum(0, start).lower():
                        raise RuntimeError("续读前缀与板端摘要不一致，拒绝安装")
                emit("backup", "完整备份原始 Flash；读取异常将只重试未完成部分", done=start, total=TOTAL, backup_path=str(backup))
                if backup.exists() and backup.stat().st_size != start:
                    raise RuntimeError("本地备份长度异常，拒绝安装")
                with backup.open("ab" if backup.exists() else "xb") as output:
                    for address in range(start, TOTAL, CHUNK):
                        data = read_segment(esp, address, CHUNK)
                        if output.write(data) != len(data):
                            raise OSError("本地备份写入不完整")
                        output.flush()
                        start = address + CHUNK
                        if start % (1024*1024) == 0:
                            emit("backup", "正在备份原始 Flash", done=start, total=TOTAL)
                break
            except Exception:
                journal['read_failures']+=1;save()
                esp._port.close()
                if attempt == 9:
                    raise RuntimeError("读取重试次数已用尽，备份未完整，未开始烧录")
                emit("backup", "读取中断，重新连接并核对已有前缀后续读", done=start, total=TOTAL)
                esp, _ = connect(port, mac,baud=115200 if attempt>=1 else 460800)
        emit("verify_backup", "核对整片板端摘要")
        data = backup.read_bytes()
        md5 = esp.flash_md5sum(0, TOTAL).lower()
        if len(data) != TOTAL or hashlib.md5(data).hexdigest() != md5:
            raise RuntimeError("整片备份校验失败，未开始烧录")
        journal.update(backup_complete=True, backup_sha256=hashlib.sha256(data).hexdigest(), backup_device_md5=md5)
        save()
        emit("flash", "备份已验证，正在写入默认固件与初始配置区", done=0, total=1)
        journal["flash_started"] = True
        save()
        cmds.write_flash(esp, images, flash_size="16MB", flash_mode="dio", flash_freq="40m", no_progress=True)
        journal["flash_complete"] = True
        save()
        emit("verify", "独立校验全部写入区域")
        cmds.verify_flash(esp, images, flash_size="16MB", flash_mode="dio", flash_freq="40m")
        journal["verified"] = True
        save()
        esp.hard_reset()
    except BaseException as exc:
        journal["error"] = str(exc)
        save()
        raise
    finally:
        esp._port.close()
    emit("boot", "固件写入校验成功，检查重启后的配置接口")
    device_id = verify_boot(port)
    if device_id != mac.replace(":", ""):
        raise RuntimeError("启动后的设备标识不匹配")
    journal["boot_verified"] = True
    save()
    emit("complete", "默认固件已安装，配置接口已响应", done=100, total=100, backup_path=str(backup))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--port", required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--backup-dir", type=Path, required=True)
    args = p.parse_args()
    try:
        install(args.port, args.manifest, args.backup_dir)
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
