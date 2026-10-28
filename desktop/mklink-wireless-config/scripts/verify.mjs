import {spawnSync} from 'node:child_process';
const sdk=process.env.MKLINK_SDK_ROOT;
if(!sdk){console.error('Set MKLINK_SDK_ROOT to the verified SDK path. See docs/BUILD.md.');process.exit(2);}
const result=spawnSync(process.env.PYTHON??'python',['../../tools/verify-source.py','--sdk',sdk],{stdio:'inherit'});
process.exit(result.status??1);
