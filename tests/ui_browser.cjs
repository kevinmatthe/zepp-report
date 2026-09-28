// Optional browser smoke test: PLAYWRIGHT_MODULE=/path/to/playwright node tests/ui_browser.cjs
// Uses isolated API fixtures; never connects to a real Zepp account.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}), args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage(); const errors = []; const writes = [];
    page.on('pageerror', e => errors.push(e.message));
    let authenticated = false, empty = false, dense = false, delayNextData = false, activeStatus = 0, maxStatus = 0;
    const dataQueries = [];
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    const settings = { user_id: 'test-user', account: 'test', region: 'global', timezone: 'Asia/Shanghai', interval_minutes: 30, initial_days: 30, lookback_days: 3, configured: true, token_configured: true, vm_url: 'http://vm.test/import' };
    const timestamp = Date.now();
    await page.route('http://zepp.test/**', async route => {
      const request = route.request(), url = new URL(request.url());
      if (!url.pathname.startsWith('/api/')) {
        const filename = url.pathname === '/' ? 'index.html' : path.basename(url.pathname);
        return route.fulfill({ status: 200, contentType: filename.endsWith('.css') ? 'text/css' : filename.endsWith('.js') ? 'application/javascript' : 'text/html', body: fs.readFileSync(path.join(__dirname, '../zepp_report/static', filename), 'utf8') });
      }
      const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
      if (request.method() !== 'GET') { assert.equal(request.headers()['x-zepp-request'], '1'); assert.equal(request.headers()['content-type'], 'application/json'); writes.push({ path: url.pathname, body: request.postDataJSON() }); }
      if (url.pathname === '/api/login') { authenticated = request.postDataJSON().password === 'test-password'; return reply(authenticated ? { ok: true } : { detail: 'bad password' }, authenticated ? 200 : 401); }
      if (!authenticated) return reply({ detail: 'unauthorized' }, 401);
      if (url.pathname === '/api/logout') { authenticated = false; return reply({ ok: true }); }
      if (url.pathname === '/api/settings') { if (request.method() === 'PUT') Object.assign(settings, request.postDataJSON()); return reply(settings); }
      if (url.pathname === '/api/status') { activeStatus++; maxStatus = Math.max(maxStatus, activeStatus); await delay(40); activeStatus--; return reply({ configured: true, auth_required: false, worker_alive: true, last_success: timestamp / 1000, next_sync: timestamp / 1000 + 1800, pending_exports: 0, conflicts: 0, tasks: { pending: 0, failed: 1, done: 1, running: 0 }, recent_tasks: [{ day: '2026-09-28', kind: 'sleep', status: 'done', updated_at: timestamp / 1000 }] }); }
      if (url.pathname === '/api/retry') return reply({ queued: 1 });
      if (url.pathname === '/api/sync') return reply({ queued: 3 });
      if (url.pathname === '/api/data') { dataQueries.push(url.search); const isEmpty = empty; if (delayNextData) { delayNextData = false; await delay(300); } return reply({ timezone: 'Asia/Shanghai', days: isEmpty ? [] : [{ date: '2026-09-28', summary: { steps: 1234, sleep_minutes: 430, sleep_score: 83, tsb: -4 }, heart_rate: dense ? Array.from({ length: 120000 }, (_, i) => ({ time: timestamp + i * 1000 + (i >= 60000 ? 3600000 : 0), value: i === 32000 ? 190 : 60 + (i % 20) })) : [{ time: timestamp, value: 65 }, { time: timestamp + 60000, value: 75 }, { time: timestamp + 3600000, value: 85 }], stress: [{ time: timestamp, value: 20 }], sleep_stages: [{ start: timestamp - 3600000, end: timestamp - 1800000, stage: 'deep' }, { start: timestamp - 1800000, end: timestamp, stage: 'rem' }] }] }); }
      return reply({ detail: 'not found' }, 404);
    });
    await page.goto('http://zepp.test/');
    await page.locator('#login-view').waitFor({ state: 'visible' });
    await page.getByLabel('管理密码').fill('wrong'); await page.getByRole('button', { name: '登录 →' }).click();
    await page.getByText('密码不正确，请重试。').waitFor();
    await page.getByLabel('管理密码').fill('test-password'); await page.getByRole('button', { name: '登录 →' }).click();
    await page.locator('#heart-chart svg').waitFor();
    assert.equal(await page.locator('#heart-chart path').first().getAttribute('d').then(d => (d.match(/M/g) || []).length), 2, 'large sampling gap must break chart line');
    assert.equal(await page.locator('.metric-value').nth(1).innerText(), '—km', 'missing distance must not become zero');
    for (const width of [375, 414, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 950 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `horizontal page overflow at ${width}`);
      await page.getByRole('button', { name: '设置', exact: true }).click();
      await page.locator('#settings-dialog').waitFor({ state: 'visible' });
      assert.equal(await page.locator('input[name="token"]').inputValue(), '', 'token never echoed');
      assert.equal(await page.evaluate(() => document.querySelector('dialog[open]').scrollWidth > document.querySelector('dialog[open]').clientWidth), false, `dialog overflow at ${width}`);
      await page.getByRole('button', { name: '关闭设置' }).click();
      if (process.env.UI_SCREENSHOT_DIR) { fs.mkdirSync(process.env.UI_SCREENSHOT_DIR, { recursive: true }); await page.screenshot({ path: path.join(process.env.UI_SCREENSHOT_DIR, `dashboard-${width}.png`), fullPage: true }); }
    }
    await page.getByRole('button', { name: '设置', exact: true }).click();
    await page.getByRole('button', { name: '保存设置' }).click();
    await page.locator('#settings-dialog').waitFor({ state: 'hidden' });
    assert.equal(writes.find(w => w.path === '/api/settings').body.token, '');
    await page.getByRole('button', { name: '历史补数', exact: true }).click();
    await page.getByRole('button', { name: '加入同步队列' }).click();
    await page.locator('#backfill-dialog').waitFor({ state: 'hidden' });
    assert.ok(writes.find(w => w.path === '/api/sync').body.from_date);
    assert.equal(writes.find(w => w.path === '/api/sync').body.force, false);
    await page.getByRole('button', { name: '历史补数', exact: true }).click();
    await page.getByLabel('重新获取已完成数据').check();
    await page.getByRole('button', { name: '加入同步队列' }).click();
    await page.locator('#backfill-dialog').waitFor({ state: 'hidden' });
    assert.equal(writes.filter(w => w.path === '/api/sync').at(-1).body.force, true);
    await page.getByRole('button', { name: '重试失败项', exact: true }).click();
    await page.getByText('已重新加入队列：1 个失败任务').waitFor();
    assert.ok(writes.find(w => w.path === '/api/retry'));
    await page.locator('#from-date').fill('2026-09-01'); await page.locator('#to-date').fill('2026-09-03');
    await page.getByRole('button', { name: '查看', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#period-caption').textContent.startsWith('2026-09-01 — 2026-09-03'));
    assert.ok(dataQueries.at(-1).includes('from_date=2026-09-01&to_date=2026-09-03'));
    assert.ok((await page.locator('#export').getAttribute('href')).includes('from_date=2026-09-01&to_date=2026-09-03'));
    dense = true; await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#heart-chart svg')?.getAttribute('aria-label').includes('120000'));
    const densePath = await page.locator('#heart-chart path').first().getAttribute('d');
    assert.equal((densePath.match(/M/g) || []).length, 2, 'pixel sampling must preserve original gaps');
    assert.ok((densePath.match(/[ML]/g) || []).length < 2400, '120k samples should use less than 2400 drawing points');
    assert.ok(await page.locator('#heart-chart').innerText().then(text => text.includes('209') || text.includes('210')), 'spike remains in raw-data axis extent');
    dense = false;
    const count = dataQueries.length; await page.locator('#from-date').fill('2026-09-04');
    await page.getByRole('button', { name: '查看', exact: true }).click();
    await page.getByText('请选择有效日期，开始日期不能晚于结束日期。').waitFor();
    assert.equal(dataQueries.length, count, 'invalid date window must not send request');
    await page.locator('#from-date').fill('2026-09-01');
    delayNextData = true; await page.getByRole('button', { name: '刷新', exact: true }).click();
    while (dataQueries.length === count) await delay(10);
    empty = true; await page.getByRole('button', { name: '查看', exact: true }).click();
    await page.getByText('暂无归档数据。配置账号后点击“立即同步”，或选择其他日期。').waitFor();
    await delay(400);
    assert.equal(await page.locator('#heart-chart svg').count(), 0, 'older response must not overwrite latest empty response');
    await page.evaluate(() => { const button = document.querySelector('#refresh'); for (let i = 0; i < 3; i++) button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    await delay(150); assert.equal(maxStatus, 1, 'status requests must not overlap');
    await page.getByRole('button', { name: '退出', exact: true }).click();
    await page.locator('#login-view').waitFor({ state: 'visible' });
    assert.deepEqual(errors, []);
    console.log('UI browser smoke passed: auth, CSRF, settings, backfill, sampling gaps, missing/empty data, responsive 375/414/768/1024/1440.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
