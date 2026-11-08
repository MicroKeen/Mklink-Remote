"""Package a qualified version without overwriting previous releases.

Acceptance contains summaries/hashes, never target backups or pairing secrets.
Desktop shortcut creation is separate from successful packaging.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import zipfile


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def qualification_complete(acceptance, version):
    restored = all(acceptance.get(k) is True for k in ('target_original_restored', 's3_config_restored'))
    companion = acceptance.get('state') == 'PASS' and acceptance.get('c6_companion_running') is True
    deferred = (acceptance.get('state') == 'PASS_WITH_DEFERRED_COMPANION' and
                acceptance.get('c6_companion_running') is False and
                acceptance.get('c6_companion_deferred_by_user') is True)
    retained = (acceptance.get('state') == 'PASS_WITH_RETAINED_FIXTURE' and
                acceptance.get('c6_companion_running') is False and
                acceptance.get('c6_fixture_retained_by_user') is True and
                acceptance.get('c6_fixture_unchanged') is True)
    return (restored and acceptance.get('desktop_version') == version and
            (retained or ((companion or deferred) and acceptance.get('c6_original_restored') is True)))


def qualified_firmware(manifest, acceptance):
    apps = [image for image in manifest['images'] if image['address'] == 0x10000]
    return (manifest['version'] == acceptance.get('s3_firmware') and len(apps) == 1 and
            apps[0]['sha256'] == acceptance.get('s3_app_sha256'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--acceptance',type=Path,required=True)
    args=parser.parse_args()
    app=Path(__file__).resolve().parents[1]
    version=json.loads((app/'package.json').read_text(encoding='utf-8'))['version']
    acceptance=json.loads(args.acceptance.read_text(encoding='utf-8'))
    if not qualification_complete(acceptance, version):
        raise SystemExit('Qualification/recovery incomplete or version mismatch; release not promoted')
    helper=app/'src-tauri/resources/device-tool/mklink-target-tool.exe'
    if sha256(helper)!=acceptance.get('target_helper_sha256'):
        raise SystemExit('Native helper differs from qualified hardware artifact')
    firmware=app/'src-tauri/resources/firmware'
    fw=json.loads((firmware/'manifest.json').read_text(encoding='utf-8'))
    if not qualified_firmware(fw,acceptance):raise SystemExit('Bundled firmware differs from qualified APP hash/version')
    for name in ['mklink-remote.exe','mklink-wireless-config.exe']:
        if sha256(app/'src-tauri/target/release'/name)!=acceptance.get('executables',{}).get(name):raise SystemExit('Desktop/CLI differs from qualification')
    if sha256(app/'src-tauri/resources/device-tool/remote-server/mklink-remote-server.exe')!=acceptance.get('remote_server_sha256'):raise SystemExit('Private server differs from qualification')
    if not acceptance.get('original_skill_unchanged') or not acceptance.get('original_mcp_unchanged'):raise SystemExit('Original boundary not verified')
    if not all(acceptance.get('routes',{}).get(mode,{}).get('state')=='PASS' for mode in ('sta','ap','ble')):raise SystemExit('Three physical routes not qualified')
    for entry in fw['images']:
        if sha256(firmware/entry['file'])!=entry['sha256']:raise SystemExit('Bundled firmware hash mismatch')
    out=app/'output/releases';out.mkdir(parents=True,exist_ok=True)
    portable=out/f'MklinkRemote-{version}-x64'
    installer=out/f'MklinkRemote-{version}-x64-setup.exe'
    archive=out/f'MklinkRemote-{version}-x64-portable.zip'
    manifest_path=out/f'release-manifest-{version}.json'
    if any(p.exists() for p in (portable,installer,archive,manifest_path)):
        raise SystemExit('Version already packaged; existing artifacts preserved')
    source_installer=app/f'src-tauri/target/release/bundle/nsis/Mklink 无线工作台_{version}_x64-setup.exe'
    executable=app/'src-tauri/target/release/mklink-wireless-config.exe'
    firmware_zip=out/f"mklink-n16r8-default-{fw['version']}.zip"
    if not all(p.is_file() for p in (source_installer,executable,firmware_zip)):
        raise SystemExit('Build desktop/NSIS and firmware archive before packaging')
    if sha256(source_installer)!=acceptance.get('installer_sha256'):
        raise SystemExit('Installer differs from qualified installed artifact')
    portable.mkdir()
    shutil.copy2(executable,portable/'MklinkRemote.exe')
    shutil.copy2(app/'src-tauri/target/release/mklink-remote.exe',portable/'mklink-remote.exe')
    resources=json.loads((app/'src-tauri/tauri.conf.json').read_text(encoding='utf8'))['bundle']['resources']
    for source,target in resources.items():
        if target=='mklink-remote.exe':continue
        src=app/'src-tauri'/source;dest=portable/target
        dest.parent.mkdir(parents=True,exist_ok=True)
        if src.is_dir():shutil.copytree(src,dest)
        else:shutil.copy2(src,dest)
    shutil.copy2(app/'README.md',portable/'README.md')
    # Publish only curated docs; the developer tree can also hold private HIL
    # reports. Never copy the entire local docs directory into a release.
    docs=portable/'docs';docs.mkdir(exist_ok=True)
    shutil.copy2(app/'docs/AGENT-CLI.md',docs/'AGENT-CLI.md')
    root=app.parents[1]
    for name in ['BUILD.md','ARCHITECTURE.md','HARDWARE.md','TESTING.md','RELEASING.md','VALIDATION-0.8.0.md','VALIDATION-0.8.1.md','ANDROID.md']:
        shutil.copy2(root/'docs'/name,docs/name)
    for name in ['LICENSE','THIRD_PARTY_NOTICES.md']:
        shutil.copy2(root/name,portable/name)
    shutil.copy2(args.acceptance,portable/'qualification.json')
    shutil.copy2(source_installer,installer)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,strict_timestamps=False) as z:
        for path in sorted(portable.rglob('*')):
            if path.is_file():z.write(path,path.relative_to(out))
    manifest=dict(desktop=version,s3_firmware=fw['version'],qualification=acceptance,files=[])
    for path in [installer,archive,firmware_zip]:
        manifest['files'].append(dict(file=path.name,bytes=path.stat().st_size,sha256=sha256(path)))
    for path in [manifest_path,out/'release-manifest.json']:
        path.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    latest=dict(version=version,executable=str((portable/'MklinkRemote.exe').resolve()))
    (app/'output/current-release.json').write_text(json.dumps(latest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(latest,ensure_ascii=False))


if __name__=='__main__':main()
