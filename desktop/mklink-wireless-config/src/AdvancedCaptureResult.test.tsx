import {it,expect} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import AdvancedCaptureResult from './AdvancedCaptureResult';
it('distinguishes parser loss from sample loss and never fills missing evidence with zero',()=>{
 const missing=renderToStaticMarkup(<AdvancedCaptureResult action="superwatch" result={{samples:12}}/>);
 expect(missing).toContain('解析丢帧');expect(missing).toContain('CRC 错误');expect(missing).toContain('—');expect(missing).toContain('停止应答未单独报告');
 const complete=renderToStaticMarkup(<AdvancedCaptureResult action="superwatch" result={{stats:{parser_dropped_frames:2,parser_crc_errors:1},mux_stop_verified:true,stop_and_drain_ms:210}}/>);
 expect(complete).toContain('210 ms');expect(complete).toContain('本次已收到匹配的停止应答');
});
