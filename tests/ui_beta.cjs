const {chromium}=require('@playwright/test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox'],...process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{}});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.clock.install();
  let authenticated=false,empty=false,fail=false,offline=false,statusFail=false;
  let archived=Math.floor(Date.now()/1000);const errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('http://beta.test/**',async route=>{
   const url=new URL(route.request().url()),p=url.pathname;
   const reply=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
   if(!p.startsWith('/api/'))return route.fulfill({contentType:p.endsWith('.js')?'application/javascript':p.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(__dirname,'../zepp_report/static',p.startsWith('/beta')?'beta.html':p.replace('/static/','')))});
   if(p==='/api/login'){authenticated=true;assert.equal(route.request().headers()['x-zepp-request'],'1');return reply({ok:true});}
   if(!authenticated)return reply({detail:'请先登录'},401);
   if(p==='/api/logout'){authenticated=false;return reply({ok:true});}
   if(p==='/api/settings')return reply({timezone:'Asia/Shanghai'});
   if(p==='/api/status')return statusFail?reply({detail:'offline'},503):reply({configured:true,worker_alive:!offline,last_success:archived,tasks:{done:1}});
   requests.push(url.search);
   if(p.startsWith('/api/days/'))return reply({date:p.split('/').at(-1),profiles:Object.fromEntries([['heart_rate',72],['spo2',98],['stress',25]].map(([key,value])=>[key,Array.from({length:288},(_,i)=>({minute:i*5,value:value+Math.sin(i/12)*(key==='spo2'?.4:5)}))])),heart_rate:[{time:Date.now(),value:72}],spo2:[{time:Date.now(),value:98}]});
   if(p==='/api/analytics/profile')return reply({buckets:Array.from({length:288},(_,i)=>({minute:i*5,n:7,...Object.fromEntries(Array.from({length:101},(_,p)=>['p'+p,(url.searchParams.get('metric')==='spo2'?98+(p-50)/50:70+(p-50)/4)+Math.sin(i/12)*(url.searchParams.get('metric')==='spo2'?.3:4)]))}))});
   if(fail)return reply({detail:'测试读取失败'},500);
   const from=url.searchParams.get('from_date'),to=url.searchParams.get('to_date'),compare=url.searchParams.get('compare');
   const count=Math.round((Date.parse(to)-Date.parse(from))/86400000)+1;
   const shift=(s,n)=>new Date(Date.parse(s+'T12:00:00Z')+n*86400000).toISOString().slice(0,10);
   if(p==='/api/analytics/distributions')return reply({days:Array.from({length:count},(_,i)=>({date:shift(from,i),heart_rate:Object.fromEntries(Array.from({length:101},(_,p)=>['p'+p,68+Math.sin(i)*3+(p-50)/4])),spo2:Object.fromEntries(Array.from({length:101},(_,p)=>['p'+p,98+(p-50)/50]))}))});
   const previous=from<'2026-09-01';
   const comparison=compare==='none'?null:compare==='year'?{from_date:'2025'+from.slice(4),to_date:'2025'+to.slice(4)}:{from_date:shift(from,-count),to_date:shift(from,-1)};
   if(from==='2026-09-03')await new Promise(r=>setTimeout(r,250));
   return reply({from_date:from,to_date:to,comparison,days:Array.from({length:count},(_,i)=>({date:shift(from,i),summary:empty?{}:{actual_sleep_minutes:400,sleep_deep_minutes:(previous?68:80)+(i%7-3)*4,steps:i===1?0:previous?6000:7500,resting_hr:previous?59:57,spo2_avg:previous?97:98},heart_rate:empty?{}:{p50:(previous?70:68)+Math.sin(i)*3},spo2:empty?{}:{mean:previous?97:98}}))});
  });
  await page.goto('http://beta.test/beta?from=2026-09-01&to=2026-09-28');
  await page.locator('#login-view').waitFor({state:'visible'});
  await page.getByLabel('管理密码').fill('beta-test-password');await page.getByRole('button',{name:'登录 Beta →'}).click();
  await page.locator('#sleep-chart canvas').waitFor();
  assert.equal(await page.locator('#metrics .metric').count(),4);
  await page.waitForFunction(()=>document.querySelector('#live-state').dataset.active==='true');
  assert.equal(await page.locator('#metrics .metric-icon').count(),4);
  await page.locator('#sleep-band-low').fill('50');await page.locator('#sleep-band-low').press('Tab');
  await page.waitForFunction(()=>document.querySelector('#sleep-distribution').textContent.includes('P50–P75'));
  await page.locator('#sleep-band-high').fill('90');await page.locator('#sleep-band-high').press('Tab');
  assert.ok((await page.locator('#sleep-distribution').innerText()).includes('P50–P90'));
  assert.equal(await page.locator('#sleep-band-low').getAttribute('max'),'85');
  await page.locator('#sleep-band-low').fill('25');await page.locator('#sleep-band-low').press('Tab');
  assert.ok((await page.locator('#sleep-distribution').innerText()).includes('P25–P90'));
  await page.locator('#sleep-band-high').fill('75');await page.locator('#sleep-band-high').press('Tab');
  await page.locator('#sleep-band-show').uncheck();
  assert.ok((await page.locator('#sleep-distribution').innerText()).includes('色带已隐藏'));
  await page.locator('#sleep-band-show').check();
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('.breathing-dot').evaluate(e=>getComputedStyle(e).animationName),'none');
  await page.emulateMedia({reducedMotion:'no-preference'});

  await page.locator('#profile-chart canvas').waitFor();
  for(const key of ['heart','spo2','profile']){
   await page.locator(`#${key}-band-low`).fill('50');await page.locator(`#${key}-band-low`).press('Tab');
   assert.equal(await page.locator(`#${key}-band-label`).innerText(),'P50–P75');
   await page.locator(`#${key}-band-high-range`).focus();await page.keyboard.press('ArrowRight');
   assert.equal(await page.locator(`#${key}-band-label`).innerText(),'P50–P80');
   await page.locator(`#${key}-band-low`).fill('25');await page.locator(`#${key}-band-low`).press('Tab');await page.locator(`#${key}-band-high`).fill('90');await page.locator(`#${key}-band-high`).press('Tab');
   assert.ok((await page.locator(`#${key}-legend`).innerText()).includes('P25–P90'));
   await page.locator(`#${key}-band-low`).fill('95');await page.locator(`#${key}-band-low`).press('Tab');
   assert.equal(await page.locator(`#${key}-band-low`).inputValue(),'85','bounds cannot cross');
   await page.locator(`#${key}-band-controls [data-preset-band="25,75"]`).click();
  }
  await page.locator('#profile-prev').click();
  await page.waitForFunction(()=>document.querySelector('#profile-status').textContent.startsWith('2026-09-27'));
  await page.locator('#profile-metric').selectOption('spo2');
  await page.waitForFunction(()=>document.querySelector('#profile-status').textContent.includes('2026-09-27'));
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
   await page.locator('#heart-band-low-range').scrollIntoViewIfNeeded();
   const thumb=await page.locator('#heart-band-low-range').boundingBox();
   const radius=width<=500?13:11;
   await page.mouse.move(thumb.x+radius+(thumb.width-2*radius)*.25,thumb.y+thumb.height/2);
   await page.mouse.down();await page.mouse.move(thumb.x+radius+(thumb.width-2*radius)*.5,thumb.y+thumb.height/2,{steps:5});await page.mouse.up();
   assert.equal(await page.locator('#heart-band-label').innerText(),'P50–P75','pointer drag '+width);
   await page.locator('#heart-band-controls [data-preset-band="25,75"]').click();
   for(const key of ['sleep','heart','spo2']){
    const legend=await page.locator(`#${key}-legend`).boundingBox(),chart=await page.locator(`#${key}-chart`).boundingBox();
    assert.ok(legend.y+legend.height<=chart.y+1,'legend outside plot '+key);
   }

   const heights=await page.locator('.metric').evaluateAll(es=>es.map(e=>e.getBoundingClientRect().height));
   assert.ok(Math.max(...heights)-Math.min(...heights)<2,'equal-weight cards');
   await page.screenshot({path:`/tmp/zepp-beta-${width}.png`,fullPage:true});
  }
  // Polling refreshes a range containing today when the archive changes.
  await page.locator('#include-today').click();
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('今天'));
  const before=requests.length;archived+=1;
  await page.clock.fastForward(30000);
  await page.waitForFunction(()=>document.querySelector('#results').getAttribute('aria-busy')==='false');
  await page.waitForTimeout(200);
  assert.ok(requests.length>before,'archive change refreshes today curve');
  offline=true;await page.clock.fastForward(30000);
  await page.waitForFunction(()=>document.querySelector('#live-label').textContent==='同步服务离线');
  assert.equal(await page.locator('#live-state').getAttribute('data-active'),'false');
  statusFail=true;await page.clock.fastForward(30000);
  await page.waitForFunction(()=>document.querySelector('#live-label').textContent.includes('连接中断'));
  statusFail=false;offline=false;
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
