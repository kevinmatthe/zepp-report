const { chromium } = require("@playwright/test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"], ...process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {} });
  try {
    const page = await browser.newPage();
    const errors = [], queries = [], writes = [];
    let dailySteps=7500, oxygenMissing=false;
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("http://zepp.test/**", async (r) => {
      const u = new URL(r.request().url()), p = u.pathname;
      const reply = (x) => r.fulfill({ contentType: "application/json", body: JSON.stringify(x) });
      if (!p.startsWith("/api/")) return r.fulfill({ contentType: p.endsWith(".js") ? "application/javascript" : p.endsWith(".css") ? "text/css" : "text/html", body: fs.readFileSync(path.join(__dirname, "../zepp_report/static", p === "/" ? "index.html" : p.replace("/static/", ""))) });
      if (r.request().method() !== "GET") {
        writes.push({ path: p, body: r.request().postDataJSON() });
        return reply({ queued: 6, total: 12, done: 6, unrequested: 6 });
      }
      queries.push(p + u.search);
      if (p === "/api/settings") return reply({ timezone: "Asia/Shanghai", user_id: "fixture", token_configured: true, interval_minutes:45, lookback_days:4 });
      if (p === "/api/status") return reply({ configured: true, worker_alive: true, tasks: { done: 6 }, analytics: { ready: 30 }, last_success:1700000000, next_sync:Math.floor(Date.now()/1000)+120 });
      if (p === "/api/tasks") return reply({tasks:[{day:"2026-09-06",kind:"band",status:"failed",attempts:2,updated_at:1700000000,error:"fixture"}],total:25,offset:Number(u.searchParams.get("offset"))});
      if (p === "/api/coverage") return reply({ today: "2026-09-28", days: Array.from({ length: 28 }, (_, i) => ({ date: `2026-09-${String(i + 1).padStart(2, "0")}`, status: i === 5 ? "running" : i === 6 ? "failed" : "done", expected: 6, archived: 6, counts: { done: 6 }, tasks: [{ kind: "band", status: "done", archived: true, has_data: true }] })) });
      if (p === "/api/analytics/profile") {
        const oxygen=u.searchParams.get('metric')==='spo2';
        return reply({buckets:Array.from({length:288},(_,i)=>({minute:i*5,n:oxygen&&oxygenMissing?0:20,mean:oxygen?(oxygenMissing?null:97.6):65,p25:oxygen?(oxygenMissing?null:97):60,p50:oxygen?(oxygenMissing?null:98):65,p75:oxygen?(oxygenMissing?null:99):75,p10:oxygen?(oxygenMissing?null:96):55,p90:oxygen?(oxygenMissing?null:100):85}))});
      }
      if (p.startsWith("/api/days/")) return reply({ date: p.split("/").at(-1), profiles: { heart_rate: [{ minute: 0, value: 75 }], stress: [], spo2:[{minute:0,value:98},{minute:5,value:null}] }, coverage:{spo2:{observed_minutes:1,expected_minutes:1440,n:1}}, summary: { steps: 7e3 }, activities: [], sleep_stages: [] });
      return reply({ timezone: "Asia/Shanghai", days: Array.from({ length: 28 }, (_, i) => ({ date: `2026-09-${String(i + 1).padStart(2, "0")}`, summary: { steps: 6e3 + i * 120, actual_sleep_minutes: 430, walking_minutes: 35 }, spo2:oxygenMissing?{n:0,p50:null,p25:null,p75:null,mean:null}:{n:20,p25:97,p50:98,p75:99,mean:97.6}, heart_rate: { n: 100, p25: 60, p50: 68, p75: 77, mean: 69 }, stress: { n: 30, p25: 20, p50: 30, p75: 40 } })), summary: { spo2_avg:{value:oxygenMissing?null:97.6,valid_days:oxygenMissing?0:28,total_days:30}, steps: { value: dailySteps*28, day_mean: dailySteps, aggregation: "sum", unit: "步", valid_days: 28, total_days: 30, previous: 182e3, previous_day_mean: 6500, previous_valid_days: 28, previous_total_days: 30, delta: 28e3, quality: "partial", comparison_quality: "complete" } } });
    });
    await page.goto("http://zepp.test/?from=2026-09-01&to=2026-09-28");
    await page.locator("#profile-chart canvas").waitFor();
    assert.ok((await page.locator(".metric-value").first().innerText()).includes("7,500"), "daily card must use day_mean, never total");
    await page.locator('#spo2-chart canvas').waitFor();
    assert.equal(await page.locator('#spo2-value').innerText(),'97.6','blood oxygen headline uses observed mean');
    await page.locator('#profile-metric').selectOption('spo2');
    await page.waitForTimeout(100);
    assert.ok(queries.some(q=>q.startsWith('/api/analytics/profile?')&&q.includes('metric=spo2')),'typical-day requests blood oxygen baseline');
    assert.ok((await page.locator('#day-detail').innerText()).includes('血氧：观测 1 / 1,440 分钟'),'blood oxygen coverage labeled correctly');
    oxygenMissing=true;await page.locator('#refresh').click();
    await page.waitForFunction(()=>document.querySelector('#spo2-value')?.textContent==='—');
    assert.equal(await page.locator('#spo2-value').innerText(),'—','missing blood oxygen never becomes zero');
    oxygenMissing=false;await page.locator('#refresh').click();
    await page.waitForFunction(()=>document.querySelector('#spo2-value')?.textContent==='97.6');
    await page.locator('#profile-metric').selectOption('heart_rate');
    assert.equal(await page.locator('#metrics .metric').count(),8,'balanced overview contains eight actual-value cards');
    assert.equal(await page.locator('[data-metric="steps-total"] .metric-number').innerText(),'210,000','total steps is distinct from daily mean');
    assert.equal(await page.locator('[data-metric="workout-count"] .metric-number').innerText(),'—','missing workouts must not become zero');
    assert.ok((await page.locator('#sync-cadence').innerText()).includes('45'),'sync cadence comes from settings');
    assert.ok((await page.locator('#sync-cadence').innerText()).includes('4'),'lookback comes from settings');
    assert.ok((await page.locator('#sync-next').innerText()).includes('分钟'),'next sync shows actual countdown');
    assert.ok((await page.locator('#hero-observation').innerText()).includes('28'),'hero count is metric observation days');
    await page.emulateMedia({reducedMotion:'reduce'});
    assert.equal(await page.locator('.metric').first().evaluate(e=>getComputedStyle(e).animationName),'none','reduced motion disables stagger');
    await page.locator('#refresh').click();await page.waitForTimeout(150);
    assert.equal(await page.locator('.metric').first().evaluate(e=>e.getAnimations({subtree:true}).length),0,'reduced motion disables JS number animations');
    await page.emulateMedia({reducedMotion:'no-preference'});
    dailySteps=8000;
    await page.locator('#refresh').click();
    await page.waitForFunction(()=>document.querySelector('[data-metric="steps-daily"] .metric-number')?.textContent==='8,000');
    // emulateMedia updates the browser preference before its MediaQueryList change
    // event is dispatched. Observe cancellation of the actual animation, rather
    // than racing that event or allowing a natural animation finish to pass.
    await page.locator('[data-metric="steps-daily"] .metric-number').evaluate(element=>{
      const animations=element.getAnimations();
      if(!animations.length)throw new Error('changed real value did not animate');
      window.__numberMotionResult=Promise.all(animations.map(animation=>
        animation.finished.then(()=>({outcome:'finished'}),()=>({outcome:'cancelled'}))
      ));
    });
    await page.emulateMedia({reducedMotion:'reduce'});
    const motionResults=await page.evaluate(()=>window.__numberMotionResult);
    assert.ok(motionResults.every(result=>result.outcome==='cancelled'),'preference change must cancel the active number animation, not just wait for it to finish');
    assert.equal(await page.locator('[data-metric="steps-daily"]').evaluate(e=>e.getAnimations({subtree:true}).length),0,'no animations remain after preference-change cancellation');
    dailySteps=7500;await page.locator('#refresh').click();
    await page.waitForFunction(()=>document.querySelector('[data-metric="steps-daily"] .metric-number')?.textContent==='7,500');
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.waitForTimeout(100);
    const before = queries.length;
    await page.locator("#range-open").click();
    await page.locator('[data-preset="90"]').click();
    await page.locator("#range-cancel").click();
    assert.equal(queries.length, before, "cancel must not query");
    assert.ok(page.url().includes("from=2026-09-01"));
    await page.locator("#range-open").click();
    await page.locator('[data-preset="7"]').click();
    await page.locator("#range-apply").click();
    await page.waitForTimeout(100);
    assert.ok(!page.url().includes("from=2026-09-01"));
    await page.goBack();
    await page.waitForTimeout(100);
    assert.ok(page.url().includes("from=2026-09-01"));
    for (const width of [375, 768, 1440]) {
      await page.setViewportSize({ width, height: 950 });
      await page.waitForTimeout(150);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `overflow ${width}: ` + JSON.stringify(await page.evaluate(() => [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > innerWidth + 1 && !e.closest("[hidden]")).map((e) => [e.tagName, e.id, e.className, e.getBoundingClientRect().right]).slice(0, 15))));
      await page.screenshot({ path: `/tmp/zepp-ui-${width}.png`, fullPage: true });
    }
    await page.locator("#grain").selectOption("week");
    await page.waitForTimeout(150);
    assert.ok(page.url().includes("grain=week"));
    await page.locator("#range-open").click();
    await page.locator("#range-from").fill("2026-02-30");
    await page.locator("#range-apply").click();
    assert.equal(await page.locator("#range-dialog").isVisible(), true, "impossible date rejected");
    await page.locator("#range-from").fill("2024-01-01");
    await page.locator("#range-to").fill("2026-01-01");
    await page.locator("#range-apply").click();
    assert.equal(await page.locator("#range-dialog").isVisible(), true, "overlong range rejected");
    await page.locator("#range-cancel").click();
    await page.locator('[data-nav="sync"]').click();
    await page.locator('#coverage-grid.year').waitFor();
    assert.equal(await page.locator('#coverage-grid > span').count(),3,'2026 begins Thursday with three weekday placeholders');
    await page.locator('#coverage-grid [data-date="2026-09-06"]').click();
    await page.locator('[data-view="week"]').click();
    await page.locator('#coverage-grid.week').waitFor();
    assert.equal(await page.locator('#coverage-grid button').count(),56,'week is 7 days × 8 acquisition kinds');
    await page.setViewportSize({width:375,height:950});await page.waitForTimeout(150);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'week matrix scrolls inside calendar');
    await page.locator('[data-view="month"]').click();
    await page.locator('#coverage-grid.month').waitFor();
    assert.equal(await page.locator('#coverage-grid .weekday').count(),7);
    await page.locator('[data-view="day"]').click();
    await page.locator('#coverage-grid.day').waitFor();
    assert.ok((await page.locator('#coverage-detail').innerText()).includes('2026-09-06'),'day view immediately shows selected day');
    await page.locator('#selection-trends').click();
    await page.locator('#trends-view').waitFor({state:'visible'});
    assert.ok(page.url().includes('from=2026-09-06'));
    await page.locator('[data-nav="sync"]').click();
    await page.locator("#coverage-grid button").first().click();
    await page.locator('#task-records summary').click();
    await page.locator('#task-status').selectOption('failed');
    await page.locator('#task-next').click();
    await page.waitForTimeout(100);
    assert.ok(queries.some(q=>q.startsWith('/api/tasks?')&&q.includes('status=failed')&&q.includes('offset=20')),'tasks filter and pagination query');
    await page.locator('#retry-failed').click();
    assert.equal(writes.filter(w=>w.path==='/api/retry').length,0,'retry requires explicit preview and confirmation');
    await page.locator('#preview-sync').click();
    await page.locator('#confirm-sync').click();
    assert.equal(writes.filter(w=>w.path==='/api/retry').length,1);
    await page.locator("#backfill-open").click();
    await page.locator("#preview-sync").click();
    await page.locator("#confirm-sync").click();
    assert.equal(writes.filter((x) => x.path === "/api/sync").length, 1);
    assert.ok(writes.find((x) => x.path === "/api/sync").body.from_date);
    assert.ok(!queries.some((x) => x.startsWith("/api/data")));
    assert.deepEqual(errors, []);
    console.log("Trends UI: ranges, history, responsive, coverage and preview passed");
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
