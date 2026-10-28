import {copyFileSync,mkdirSync} from 'node:fs';
mkdirSync('public',{recursive:true});
copyFileSync('../../boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/main/device.html','public/device-preview.html');
