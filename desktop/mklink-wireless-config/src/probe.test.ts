import {describe,it,expect} from 'vitest';
import {probeView,verifyProbeEcho} from './probe';
import type {DeviceStatus} from './contract';
const status={usb:{connected:true,vid:0x0d28,pid:0x0202,speed:'FULL_12Mbps',invalid_bulk:0},probe:{state:'ready',ready:true,version:'V4.7.0',generation:3,in_mps:64,out_mps:64,error:''}} as DeviceStatus;
describe('V4 readiness boundary',()=>{
  it('never derives command readiness from enumeration alone',()=>{expect(probeView({...status,probe:undefined},true).ready).toBe(false);expect(probeView(status,false).ready).toBe(false);});
  it('rejects inconsistent identity, endpoint and generation state',()=>{
    expect(probeView({...status,usb:{...status.usb,vid:1}},true).ready).toBe(false);
    expect(probeView({...status,probe:{...status.probe!,in_mps:512}},true).ready).toBe(false);
    expect(probeView({...status,probe:{...status.probe!,state:'outcome_unknown'}},true).ready).toBe(false);
    expect(probeView(status,true).ready).toBe(true);
  });
  it('requires a standalone echo and complete prompt from the same USB generation',()=>{
    const reply={generation:3,reply_base64:btoa("print('__mklink_wireless_check__')\r\n__mklink_wireless_check__\r\n>>> ")};
    expect(()=>verifyProbeEcho(reply,3)).not.toThrow();expect(()=>verifyProbeEcho(reply,2)).toThrow('重新连接');
    expect(()=>verifyProbeEcho({...reply,reply_base64:btoa("print('__mklink_wireless_check__')\n>>> ")},3)).toThrow('回显');
    expect(()=>verifyProbeEcho({...reply,reply_base64:btoa('__mklink_wireless_check__\n')},3)).toThrow('回显');
  });
});
