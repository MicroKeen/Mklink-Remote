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
    const nav=page.getByRole('navigation',{name:'主导航'});
    await nav.getByRole('button',{name:'设备概览',exact:true}).click();
    if(await nav.locator('button:visible').count()!==4)throw Error('Primary navigation should expose four entries');
    if(await page.locator('.mode-overview').count())throw Error('Duplicate mode tiles remain');
    for(const name of ['链路状态明细','内存与传输缓冲','近期设备日志']){
      const summary=page.locator('summary').filter({hasText:name});await summary.focus();await page.keyboard.press('Enter');
      if(!await summary.evaluate(e=>e.parentElement.open))throw Error('Disclosure keyboard failed');await summary.click();
    }
    await page.setViewportSize({width:1360,height:1000});await page.screenshot({path:`${out}/overview-simplified.png`,fullPage:true});
    await nav.locator('summary').click();await nav.getByRole('button',{name:'网络与热点',exact:true}).click();
    await page.getByRole('heading',{name:'STA · 路由器网络'}).waitFor();
    if(await page.getByText('扫描完成；测试时请选择 C6 独立网络').count())throw Error('Fixture instructions leaked into user flow');
    await page.getByRole('button',{name:'连接设备',exact:true}).click();
    await nav.getByRole('button',{name:'独立验证工具',exact:true}).click();
    await page.getByRole('button',{name:'识别目标',exact:true}).click();
    await page.getByText('STM32F411CEUx',{exact:true}).waitFor();
    await page.getByRole('button',{name:'选择符号',exact:true}).click();
    await page.getByRole('button',{name:'开始 SuperWatch',exact:true}).click();
    await page.getByRole('button',{name:'停止采集或准备',exact:true}).click();
    await page.getByText('演示 · 正在停止并接收尾部',{exact:true}).waitFor();
    if(!await page.getByRole('button',{name:'正在停止…',exact:true}).isDisabled())throw Error('Pending STOP must not be resubmitted');
    if(!await page.getByRole('button',{name:'断开连接',exact:true}).isDisabled())throw Error('Connection must stay locked while stopping');
    await page.locator('.target-job').screenshot({path:`${out}/stop-pending.png`});
    await page.getByText('演示 · 操作完成',{exact:true}).waitFor();
    await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'帮助与说明',exact:true}).click();
    await page.getByRole('tab',{name:/Agent/}).click();await page.getByText('让 Agent 操作 Mklink Remote',{exact:true}).waitFor();
    await page.locator('summary').filter({hasText:'采集质量与性能边界'}).click();
    await page.getByText(/Wi-Fi 800 Hz 尚未稳定通过/).waitFor();
    await page.screenshot({path:`${out}/agent-updated.png`,fullPage:true});
    if(errors.length)throw Error(JSON.stringify(errors));
    writeFileSync(out+'/summary.json',JSON.stringify({ok:true,scope:'browser demo; no hardware',variants:6,empty_actions:true,pause_resume:true,agent_help:true,compact_navigation:true,disclosure_keyboard:true,stop_pending:true,no_overflow_980:true,errors},null,2));
    console.log('Browser source smoke PASS');
  }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
