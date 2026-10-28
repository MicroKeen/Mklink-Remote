// Browser-only source smoke test. The isolated preview and browser are closed.
const {chromium}=require('@playwright/test');
const {spawn}=require('node:child_process');
const {mkdirSync,writeFileSync}=require('node:fs');
const path=require('node:path');
const net=require('node:net');
async function freePort(){return new Promise((resolve,reject)=>{const s=net.createServer();s.once('error',reject);s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});}
(async()=>{
  const port=await freePort(),url=`http://127.0.0.1:${port}`;
  const server=spawn(process.execPath,[path.resolve('node_modules/vite/bin/vite.js'),'preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{stdio:'pipe',windowsHide:true});
  let browser;const errors=[];server.stderr.on('data',d=>process.stderr.write(d));
  const out='output/public-ui';mkdirSync(out,{recursive:true});
  try{
    let ready=false;for(let i=0;i<100;i++){try{if((await fetch(url)).ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,100));}
    if(!ready)throw Error('Isolated preview did not start');
    browser=await chromium.launch({headless:true});const context=await browser.newContext();const page=await context.newPage();
    page.on('pageerror',e=>errors.push(String(e)));page.on('response',r=>{if(r.status()>=400)errors.push(`HTTP ${r.status()} ${new URL(r.url()).pathname}`);});
    for(const skin of ['technical','aurora','sand'])for(const theme of ['dark','light']){
      await page.goto(url+'/?demo=1');await page.evaluate(({skin,theme})=>{localStorage.setItem('mklink-skin',skin);localStorage.setItem('mklink-theme',theme);},{skin,theme});await page.reload();
      await page.setViewportSize({width:1360,height:1000});await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'日志诊断',exact:true}).click();
      await page.getByRole('heading',{name:'运行日志'}).waitFor();
      await page.getByRole('group',{name:'日志级别'}).getByRole('button',{name:/Error/}).click();
      await page.getByLabel('搜索日志内容').fill('NO_MATCH_PUBLIC_SMOKE');
      if(!await page.getByRole('button',{name:'复制日志',exact:true}).isDisabled())throw Error('Empty copy must be disabled');
      if(!await page.getByRole('button',{name:'导出日志',exact:true}).isDisabled())throw Error('Empty export must be disabled');
      await page.getByLabel('搜索日志内容').fill('');
      await page.getByRole('button',{name:'暂停刷新',exact:true}).click();await page.getByRole('button',{name:'继续刷新',exact:true}).click();
      await page.screenshot({path:`${out}/diagnostics-${skin}-${theme}.png`,fullPage:true});
      await page.setViewportSize({width:980,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Narrow layout overflow');
    }
    await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'帮助与说明',exact:true}).click();
    await page.getByRole('tab',{name:/Agent/}).click();await page.getByText('让 Agent 操作 Mklink Remote',{exact:true}).waitFor();
    if(errors.length)throw Error(JSON.stringify(errors));
    writeFileSync(out+'/summary.json',JSON.stringify({ok:true,scope:'browser demo; no hardware',variants:6,empty_actions:true,pause_resume:true,agent_help:true,no_overflow_980:true,errors},null,2));
    console.log('Browser source smoke PASS');
  }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
