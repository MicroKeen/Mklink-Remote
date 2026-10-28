export type LogLevel='info'|'warning'|'error';
export type LogEntry={id:number;timestamp_ms:number;level:LogLevel;source:string;message:string};
export type LogSnapshot={entries:LogEntry[];total:number;matched:number;dropped:number;counts:Record<LogLevel,number>};
export function filterLogs(entries:LogEntry[],level:string,search:string){return entries.filter(e=>(level==='all'||e.level===level)&&e.message.toLocaleLowerCase().includes(search.toLocaleLowerCase()));}
export function formatLogs(entries:LogEntry[]){return entries.map(e=>`${new Date(e.timestamp_ms).toISOString()} [${e.level.toUpperCase()}] [${e.source}] ${e.message}`).join('\n');}
