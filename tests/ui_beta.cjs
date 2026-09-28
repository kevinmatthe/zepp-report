const {chromium}=require('@playwright/test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox'],...process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{}});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  let authenticated=false,empty=false,fail=false;const errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('http://beta.test/**',async route=>{
   const url=new URL(route.request().url()),p=url.pathname;
   const reply=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
   if(!p.startsWith('/api/'))return route.fulfill({contentType:p.endsWith('.js')?'application/javascript':p.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,'../zepp_report/static',p.startsWith('/beta')?'beta.html':p.replace('/static/','')))});
   if(p==='/api/login'){authenticated=true;assert.equal(route.request().headers()['x-zepp-request'],'1');return reply({ok:true});}
   if(!authenticated)return reply({detail:'请先登录'},401);
   if(p==='/api/logout'){authenticated=false;return reply({ok:true});}
   if(p==='/api/settings')return reply({timezone:'Asia/Shanghai'});
   requests.push(url.search);
   if(fail)return reply({detail:'测试读取失败'},500);
   const from=url.searchParams.get('from_date'),to=url.searchParams.get('to_date'),compare=url.searchParams.get('compare');
   const count=Math.round((Date.parse(to)-Date.parse(from))/86400000)+1;
   const shift=(s,n)=>new Date(Date.parse(s+'T12:00:00Z')+n*86400000).toISOString().slice(0,10);
   const previous=from<'2026-09-01';
   const comparison=compare==='none'?null:compare==='year'?{from_date:'2025'+from.slice(4),to_date:'2025'+to.slice(4)}:{from_date:shift(from,-count),to_date:shift(from,-1)};
   if(from==='2026-09-03')await new Promise(r=>setTimeout(r,250));
   return reply({from_date:from,to_date:to,comparison,days:Array.from({length:count},(_,i)=>({date:shift(from,i),summary:empty?{}:{actual_sleep_minutes:400,sleep_deep_minutes:previous?68:80,steps:i===1?0:previous?6000:7500,resting_hr:previous?59:57,spo2_avg:previous?97:98},heart_rate:empty?{}:{p50:previous?70:68},spo2:empty?{}:{mean:previous?97:98}}))});
  });
  await page.goto('http://beta.test/beta?from=2026-09-01&to=2026-09-28');
  await page.locator('#login-view').waitFor({state:'visible'});
  await page.getByLabel('管理密码').fill('beta-test-password');await page.getByRole('button',{name:'登录 Beta →'}).click();
  await page.locator('#sleep-chart canvas').waitFor();
  assert.equal(await page.locator('#metrics .metric').count(),4);
  assert.ok((await page.locator('[data-stat="deepShare"] .difference').innerText()).includes('+3 个百分点'));
  assert.ok((await page.locator('[data-stat="deepMinutes"] .difference').innerText()).includes('+12 分钟'));
  assert.ok((await page.locator('#periods').innerText()).includes('2026-08-04'));
  await page.getByRole('button',{name:'深睡占比',exact:true}).click();
  assert.equal(await page.locator('[data-sleep="deepShare"]').getAttribute('aria-pressed'),'true');
  assert.ok((await page.locator('#sleep-caption').innerText()).includes('百分点'));
  await page.locator('#compare').selectOption('year');
  await page.waitForFunction(()=>document.querySelector('#periods').textContent.includes('2025-09-01'));
  await page.locator('#compare').selectOption('none');
  await page.waitForFunction(()=>document.querySelector('.metric-change').textContent==='未开启对比');
  assert.equal(await page.locator('#periods .previous').count(),0);
  await page.locator('#compare').selectOption('previous');
  await page.waitForFunction(()=>document.querySelector('#periods .previous'));
  await page.locator('#from').fill('2026-09-03');await page.locator('.apply').click();
  await page.locator('#from').fill('2026-09-05');await page.locator('.apply').click();
  await page.waitForFunction(()=>document.querySelector('#periods').textContent.includes('本期 2026-09-05'));
  await page.waitForTimeout(350);
  assert.ok((await page.locator('#periods').innerText()).includes('本期 2026-09-05'),'late response cannot overwrite selected range');
  await page.locator('#from').fill('2026-09-01');await page.locator('.apply').click();
  await page.waitForFunction(()=>document.querySelector('#periods').textContent.includes('本期 2026-09-01'));
  for(const width of [375,414,768,1024,1440]){
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(200);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow '+width);
   const heights=await page.locator('.metric').evaluateAll(es=>es.map(e=>e.getBoundingClientRect().height));
   assert.ok(Math.max(...heights)-Math.min(...heights)<2,'equal-weight cards');
   await page.screenshot({path:`/tmp/zepp-beta-${width}.png`,fullPage:true});
  }
  empty=true;await page.locator('.apply').click();
  await page.waitForFunction(()=>document.querySelector('[data-metric="steps"] .metric-value').textContent.startsWith('—'));
  assert.ok((await page.locator('[data-stat="deepShare"] td').nth(1).innerText()).includes('—'));
  fail=true;await page.locator('.apply').click();await page.waitForFunction(()=>document.querySelector('#status').textContent==='测试读取失败');
  assert.equal(await page.locator('#results').isVisible(),false,'failed request must not leave stale results under a new date');
  fail=false;authenticated=false;await page.locator('.apply').click();await page.locator('#login-view').waitFor({state:'visible'});
  assert.equal(await page.locator('#main').isVisible(),false);
  assert.deepEqual(errors,[]);
  assert.ok(requests.some(q=>q.includes('from_date=2026-08-04')&&q.includes('compare=none')),'full baseline is fetched for whole-period sleep ratios');
  console.log('Beta browser: login, sleep differences, comparison modes, race, empty/error/session states and five widths passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
