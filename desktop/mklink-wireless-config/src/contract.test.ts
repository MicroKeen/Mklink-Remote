import { describe, it, expect } from 'vitest';
import { validateDraft, DeviceConfig, Status, wifiQr, type SaveDraft } from './contract';
const valid: SaveDraft={expected_revision:1,change_id:'test-change',node_name:'节点',wifi_ssid:'工作网络',gateway_url:'wss://hil.example',wifi_password:'12345678',network_mode:'AP',ap_ssid:'MklinkRemote-5ABE64',gateway_enabled:false,bench_id:'s3-test'};
describe('configuration boundary',()=>{
  it('counts UTF-8 bytes for firmware fields',()=>{
    expect(validateDraft({...valid,wifi_ssid:'中'.repeat(11)})).toContain('32 字节');
    expect(validateDraft({...valid,wifi_ssid:'中'.repeat(10)+'ab'})).toBeNull();
    expect(validateDraft({...valid,node_name:'中'.repeat(22)})).toContain('63 字节');
  });
  it('allows keeping a password, open networks, and hex PSKs',()=>{
    for(const wifi_password of [undefined,'','12345678','a'.repeat(63),'A1'.repeat(32)])expect(validateDraft({...valid,wifi_password})).toBeNull();
    for(const wifi_password of ['short','g'.repeat(64),'a'.repeat(65)])expect(validateDraft({...valid,wifi_password})).toContain('密码');
  });
  it('rejects unsupported gateway schemes and blank names',()=>{
    expect(validateDraft({...valid,gateway_url:'file:///C:/secret'})).toContain('中心地址');
    expect(validateDraft({...valid,node_name:'  '})).toContain('不能为空');
  });
  it('rejects missing or fabricated device state rather than showing online',()=>{
    expect(DeviceConfig.safeParse({revision:1}).success).toBe(false);
    expect(Status.safeParse({device:{},wifi:{state:'online'},gateway:{state:'connected'}}).success).toBe(false);
  });
  it('rejects AP password and SSID boundaries',()=>{
    expect(validateDraft({...valid,ap_password:'short'})).toContain('热点密码');
    expect(validateDraft({...valid,ap_ssid:'中'.repeat(11)})).toContain('热点名称');
    expect(validateDraft({...valid,ap_password:'a'.repeat(64)})).toContain('热点密码');
    expect(validateDraft({...valid,ap_password:'new-password'})).toBeNull();
  });
  it('rejects credential URLs and private-prefix lookalike domains',()=>{
    for(const gateway_url of ['ws://10.0.0.1.evil.example','ws://8.8.8.8','wss://user:token@hil.example','wss://hil.example/relay/control'])expect(validateDraft({...valid,gateway_url})).not.toBeNull();
    expect(validateDraft({...valid,gateway_url:'ws://192.168.50.1:8910'})).toBeNull();
  });
  it('escapes Wi-Fi QR separators',()=>{
    expect(wifiQr('Lab;A','a:b\\c,d')).toBe('WIFI:T:WPA;S:Lab\\;A;P:a\\:b\\\\c\\,d;;');
  });
});
