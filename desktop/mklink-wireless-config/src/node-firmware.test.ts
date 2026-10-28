import {describe,it,expect} from 'vitest';
import {NodeImage,NodeUpdate} from './node-firmware';
import {watchInput} from './target-contract';
describe('node OTA and advanced capture boundaries',()=>{
  it('requires OTA node project and complete SHA before preview',()=>{
    const image={path:'APP.bin',bytes:1384320,sha256:'a'.repeat(64),version:'0.6.2',project:'n16r8_wireless_gateway'};
    expect(NodeImage.parse(image).bytes).toBe(1384320);
    for(const change of[{project:'V4'},{sha256:'short'},{bytes:4194305}])expect(NodeImage.safeParse({...image,...change}).success).toBe(false);
  });
  it('rejects an unsupported upgrade state instead of enabling actions',()=>{
    expect(NodeUpdate.safeParse({protocol:1,state:'success'}).success).toBe(false);
  });
  it('keeps SuperWatch in aligned bounded SRAM',()=>{
    expect(watchInput('0x200010c8','36')).toEqual({address:0x200010c8,size:36});
    for(const [a,n]of[['0x08000000','36'],['0x20000001','4'],['0x2001fffc','8'],['0x20000000','4096']])expect(()=>watchInput(a,n)).toThrow();
  });
});
