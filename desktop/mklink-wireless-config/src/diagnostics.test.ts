import {describe,it,expect} from 'vitest';
import {filterLogs,formatLogs,type LogEntry} from './diagnostics';
const entries:LogEntry[]=[{id:1,timestamp_ms:0,level:'info',source:'device',message:'USB ready'},{id:2,timestamp_ms:1000,level:'warning',source:'device',message:'BLE retry'},{id:3,timestamp_ms:2000,level:'error',source:'agent',message:'USB timeout'}];
describe('diagnostic selection',()=>{
 it('applies level and search together, ignoring case',()=>expect(filterLogs(entries,'error','usb')).toEqual([entries[2]]));
 it('does not copy hidden entries',()=>{const text=formatLogs(filterLogs(entries,'warning',''));expect(text).toContain('[WARNING]');expect(text).not.toContain('USB');});
 it('keeps timestamp and source in copied text',()=>expect(formatLogs([entries[0]])).toBe('1970-01-01T00:00:00.000Z [INFO] [device] USB ready'));
});
