// Opt-in integration test against an isolated service with the worker disabled.
// UI_LIVE_URL and UI_LIVE_PASSWORD are required. Writes fake Zepp credentials.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const base = process.env.UI_LIVE_URL, password = process.env.UI_LIVE_PASSWORD;
  if (!base || !password) throw new Error('Set UI_LIVE_URL and UI_LIVE_PASSWORD for an isolated test service with the worker disabled.');
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}), args: ['--no-sandbox'] });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
    const page = await context.newPage(), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    assert.equal((await context.request.get(`${base}/api/settings`)).status(), 401);
    await page.goto(base); await page.locator('#login-view').waitFor({ state: 'visible' });
    await page.getByLabel('管理密码').fill(password); await page.getByRole('button', { name: '登录 →' }).click();
    await page.locator('#app-view').waitFor({ state: 'visible' });
    const cookies = await context.cookies(); assert.ok(cookies.some(c => c.httpOnly), 'session cookie must be HttpOnly');
    assert.equal((await context.request.get(`${base}/api/settings`)).status(), 200);
    assert.equal((await context.request.post(`${base}/api/sync`, { data: {} })).status(), 403, 'writes without CSRF header must be rejected');
    await page.getByRole('button', { name: '设置', exact: true }).click();
    await page.getByLabel('Zepp 用户 ID').fill('123'); await page.getByLabel('Zepp Token').fill('fake-token');
    await page.getByRole('button', { name: '保存设置' }).click(); await page.locator('#settings-dialog').waitFor({ state: 'hidden' });
    const settings = await (await context.request.get(`${base}/api/settings`)).json();
    assert.equal(settings.user_id, '123'); assert.equal(settings.token_configured, true); assert.equal(settings.token, undefined);
    await page.getByRole('button', { name: '历史补数', exact: true }).click();
    await page.locator('#backfill-form [name="from_date"]').fill('2026-09-01'); await page.locator('#backfill-form [name="to_date"]').fill('2026-09-02');
    const queued = page.waitForResponse(r => r.url().endsWith('/api/sync') && r.request().method() === 'POST');
    await page.getByRole('button', { name: '加入同步队列' }).click();
    const syncResponse = await queued; assert.equal(syncResponse.status(), 200); assert.ok((await syncResponse.json()).queued >= 0);
    await page.locator('#backfill-dialog').waitFor({ state: 'hidden' });
    const status = await (await context.request.get(`${base}/api/status`)).json(); assert.ok(status.tasks.pending > 0);
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.getByText('暂无归档数据。配置账号后点击“立即同步”，或选择其他日期。').waitFor();
    const downloadEvent = page.waitForEvent('download'); await page.locator('#export').click(); const download = await downloadEvent;
    assert.equal(await download.failure(), null); const downloaded = fs.readFileSync(await download.path(), 'utf8'); assert.equal(downloaded.trim(), '', 'empty database export must contain no invented rows');
    fs.mkdirSync('/tmp/zepp-ui-screens', { recursive: true }); await page.screenshot({ path: '/tmp/zepp-ui-screens/live.png', fullPage: true });
    await page.getByRole('button', { name: '退出', exact: true }).click(); await page.locator('#login-view').waitFor({ state: 'visible' });
    assert.equal((await context.request.get(`${base}/api/settings`)).status(), 401);
    assert.deepEqual(errors, []);
    console.log('Live browser E2E passed: cookie login, CSRF rejection, settings write/read with secret redaction, history queue, status, empty JSONL download, logout.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
