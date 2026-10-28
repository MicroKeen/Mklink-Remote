import {z} from 'zod';
export const TargetIdentity=z.object({part:z.literal('STM32F411CEUx'),uid:z.string().regex(/^[0-9a-f]{24}$/i),debug_id:z.string(),flash_bytes:z.literal(524288),option_control:z.string()});
export const TargetJobSchema=z.object({id:z.string(),node_id:z.string(),running:z.boolean(),action:z.string(),phase:z.string(),done:z.number(),total:z.number(),error:z.string(),result:z.unknown(),rtt:z.array(z.object({kind:z.literal('rtt'),channel:z.number(),data_hex:z.string()})),display_dropped_frames:z.number()});
export type TargetJob=z.infer<typeof TargetJobSchema>;
export type TargetInfo=z.infer<typeof TargetIdentity>;
export type TargetRequest={action:'inspect'|'identify'|'read'|'write'|'prepare_flash'|'flash'|'verify_flash'|'benchmark'|'rtt'|'superwatch'|'rtos_trace'|'binary_read'|'performance';node_id:string;project_root:string;axf?:string;params:Record<string,unknown>};
export const emptyTargetJob:TargetJob={id:'',node_id:'',running:false,action:'',phase:'idle',done:0,total:0,error:'',result:null,rtt:[],display_dropped_frames:0};
export const ArtifactInfo=z.object({path:z.string(),sha256:z.string().length(64),internal_bytes:z.number(),base:z.number(),end:z.number(),excluded_external_segments:z.array(z.object({address:z.number(),bytes:z.number()})),rtt_address:z.number().nullable().optional()});
export type Artifact=z.infer<typeof ArtifactInfo>;
export const PreparedPlan=z.object({state:z.literal('PREPARED'),target:TargetIdentity,source:ArtifactInfo,image:z.object({path:z.string(),base:z.number(),bytes:z.number(),sha256:z.string().length(64)}),original_backup:z.string(),backup_verified:z.literal(true),plan_path:z.string(),plan_sha256:z.string().length(64)});
export function integer(text:string){if(!/^(?:0x[0-9a-f]+|\d+)$/i.test(text.trim()))throw Error('请输入十进制整数或0x开头的十六进制地址');const n=Number(text.trim());if(!Number.isSafeInteger(n)||n<0||n>0xffffffff)throw Error('地址或数值超出32位范围');return n;}
export function memoryRead(address:string,size:string){const a=integer(address),n=integer(size);if(n<1||n>4096||!([[0x08000000,0x08080000],[0x20000000,0x20020000]].some(([s,e])=>a>=s&&a+n<=e)))throw Error('仅支持内部Flash或SRAM，单次1–4096字节');return {address:a,size:n};}
export function ramWrite(address:string,text:string){const a=integer(address),hex=text.replace(/\s/g,'');if(!/^(?:[0-9a-f]{2})+$/i.test(hex)||hex.length>8192)throw Error('请填写完整十六进制字节，最多4096字节');if(a<0x20000000||a+hex.length/2>0x20020000)throw Error('写入仅限STM32F411的128KiB SRAM');return {address:a,data_hex:hex};}
export function rttInput(address:string,text:string){const a=integer(address);if(a%4||a<0x20000000||a>=0x20020000)throw Error('RTT控制块必须位于SRAM内且4字节对齐');if(new TextEncoder().encode(text).length>256)throw Error('RTT下行单次最多256个UTF-8字节');return a;}
export function watchInput(address:string,size:string){const a=integer(address),n=integer(size);if(a%4||n<4||n>256||a<0x20000000||a+n>0x20020000)throw Error('SuperWatch仅支持4字节对齐的SRAM地址，单区4–256字节');return {address:a,size:n};}
export function decodeHex(hex:string){return new TextDecoder().decode(Uint8Array.from(hex.match(/.{2}/g)??[],s=>parseInt(s,16)));}
