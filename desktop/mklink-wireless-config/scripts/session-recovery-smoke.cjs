const {chromium}=require('@playwright/test');
const {spawn}=require('node:child_process');
const {mkdirSync,writeFileSync}=require('node:fs');
const net=require('node:net');

(async()=>{
  const socket=net.createServer();await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
  const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
  const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{stdio:'pipe',windowsHide:true});
  const url=`http://127.0.0.1:${port}`,out='output/session-recovery';mkdirSync(out,{recursive:true});
  let browser;const errors=[];
  try{
    let ready=false;for(let n=0;n<100;n++){try{if((await fetch(url)).ok){ready=true;break;}}catch{}await new Promise(resolve=>setTimeout(resolve,100));}
    if(!ready)throw Error('Preview did not start');
    browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1360,height:1000}});
    page.on('pageerror',e=>errors.push(String(e)));
    await page.addInitScript(()=>{
      window.isTauri=true;
      localStorage.setItem('mklink-target-project','D:/fixture/project');
      let shared=true,broken=true;
      window.recoveryCalls=[];
      window.__TAURI_INTERNALS__={invoke:async(name,args)=>{
        if(name!=='agent_call')throw Error(`Unexpected native command ${name}`);
        const {method,params}=args;window.recoveryCalls.push({method,params});
        if(method==='preferences_get')return {theme:'dark',skin:'technical',page:'shared',revision:0};
        if(method==='preferences_set')return params;
        if(method==='list_ports')return [];
        if(method==='target_job')return {running:false,action:'',phase:'idle',done:0,total:0,error:'',detail:'',result:{},stop_requested:false};
        if(method==='install_job')return {running:false,stage:'idle',done:0,total:0,error:'',detail:'',backup_path:''};
        if(method==='service_status')return {management:{connected:false,transport:'none',revision:0},shared};
        if(method==='get_logs')return [];
        if(method==='disconnect')return {accepted:true};
        if(method==='shared_control'){
          if(params.method==='saved_nodes')return [{node_id:'020000123456',transport:'http',address:'http://fixture.invalid'}];
          if(params.method==='status'&&(!shared||broken))throw Error('Shared runtime is unavailable');
          if(params.method==='detach'){shared=false;return {detached:true,backend_detach_confirmed:false,warning:'已退出本窗口；后台释放未确认，任务可能仍在运行。不要重复下载。'};}
          if(params.method==='attach'){shared=true;broken=false;}
          return {instance_id:'fixture-runtime',probe_id:'s3-020000123456',transport:'s3-http',busy:false,clients:[]};
        }
        throw Error(`Unexpected service command ${method}`);
      }};
    });
    await page.goto(url);
    const exit=page.getByRole('button',{name:'退出本窗口会话',exact:true});
    await exit.waitFor();
    await page.getByText('连接待核实',{exact:true}).waitFor();
    if(await exit.isDisabled())throw Error('Unavailable backend trapped the exit control');
    await exit.click();
    await page.getByRole('alert').filter({hasText:'后台释放未确认'}).waitFor();
    await page.getByLabel('已保存设备').click();
    await page.getByRole('option',{name:/020000123456/}).click();
    if(await page.locator('#shared-token').count())throw Error('Saved-node reconnect unexpectedly requires credentials');
    await page.getByRole('button',{name:'接入共享后台',exact:true}).click();
    await page.getByText('fixture-runtime',{exact:true}).waitFor();
    const calls=await page.evaluate(()=>window.recoveryCalls);
    const attaches=calls.filter(x=>x.method==='shared_control'&&x.params.method==='attach');
    if(attaches.length!==1||attaches[0].params.params.node_id!=='020000123456'||'node' in attaches[0].params.params)throw Error('Saved identity contract mismatch');
    if(calls.some(x=>['connect_serial','start_target','start_install'].includes(x.method)))throw Error('Recovery invoked hardware outside the shared session');
    await page.screenshot({path:`${out}/reconnected.png`,fullPage:true});
    if(errors.length)throw Error(JSON.stringify(errors));
    writeFileSync(`${out}/summary.json`,JSON.stringify({passed:true,scope:'browser with service fault double; no hardware',orphan_exit:true,unconfirmed_warning:true,saved_reconnect:true,no_credentials_in_browser:true,no_usb:true},null,2));
    console.log('Session recovery browser checks PASS');
  }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
