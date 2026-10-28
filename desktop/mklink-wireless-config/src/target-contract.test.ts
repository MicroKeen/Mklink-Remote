import {describe,it,expect} from 'vitest';
import {integer,memoryRead,ramWrite,rttInput,PreparedPlan} from './target-contract';

describe('target operation boundaries',()=>{
  it('rejects ambiguous addresses and overflowing ranges',()=>{
    for(const value of ['1e3','-1','0x','12.5','4294967296'])expect(()=>integer(value)).toThrow();
    expect(integer('0x0800C000')).toBe(0x0800c000);
    expect(()=>memoryRead('0x0807ffff','2')).toThrow();
    expect(()=>memoryRead('0x2001ffff','2')).toThrow();
    expect(()=>memoryRead('0xfffffff0','32')).toThrow();
  });
  it('permits bounded reads only in actual internal Flash or SRAM',()=>{
    expect(memoryRead('0x0807f000','4096')).toEqual({address:0x0807f000,size:4096});
    for(const [address,size] of [['0x90000000','16'],['0x40000000','4'],['0x20000000','4097'],['0x20000000','0']])expect(()=>memoryRead(address,size)).toThrow();
  });
  it('prevents direct Flash writes and incomplete hex bytes',()=>{
    expect(ramWrite('0x2001fffe','AB CD')).toEqual({address:0x2001fffe,data_hex:'ABCD'});
    for(const [address,data] of [['0x0800c000','12'],['0x2001ffff','1234'],['0x20000000','A'],['0x20000000','0x12'],['0x20000000','AA'.repeat(4097)]])expect(()=>ramWrite(address,data)).toThrow();
  });
  it('counts UTF8 bytes for one RTT message and checks alignment',()=>{
    expect(rttInput('0x20001000','汉'.repeat(85)+'A')).toBe(0x20001000);
    expect(()=>rttInput('0x20001000','汉'.repeat(86))).toThrow();
    expect(()=>rttInput('0x20001001','test')).toThrow();
    expect(()=>rttInput('0x20020000','test')).toThrow();
  });
  it('rejects a plan without independently verified backup',()=>{
    expect(PreparedPlan.safeParse({state:'PREPARED',backup_verified:false}).success).toBe(false);
  });
});
