'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { timezone: 'Asia/Shanghai', session: 0, dataRequest: 0, statusBusy: false, active: false, timer: null, fingerprint: '', settings: null };
  const number = (n, digits = 0) => n == null || !Number.isFinite(Number(n)) ? '—' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: digits });
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function formatTime(ms, options = {}) { return new Intl.DateTimeFormat('zh-CN', { timeZone: state.timezone, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', ...options }).format(new Date(ms)); }
  function dateToday() { const parts = new Intl.DateTimeFormat('en', { timeZone: state.timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date()); return ['year', 'month', 'day'].map(k => parts.find(p => p.type === k).value).join('-'); }
  function setWeek() { const today = dateToday(); const start = new Date(`${today}T12:00:00Z`); start.setUTCDate(start.getUTCDate() - 6); $('from-date').value = start.toISOString().slice(0, 10); $('to-date').value = today; }
  function notify(message, bad = false) { $('notice').textContent = message; $('notice').classList.toggle('bad', bad); $('notice').hidden = false; clearTimeout(notify.timer); notify.timer = setTimeout(() => { $('notice').hidden = true; }, 6000); }
  function loggedOut() { state.active = false; state.session++; state.dataRequest++; clearTimeout(state.timer); document.querySelectorAll('dialog[open]').forEach(d => d.close()); $('app-view').hidden = true; $('login-view').hidden = false; }
  async function api(path, method = 'GET', body) {
    const response = await fetch(path, { method, credentials: 'same-origin', headers: method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-Zepp-Request': '1' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (response.status === 401) { if (state.active) loggedOut(); throw new Error(path === '/api/login' ? '密码不正确，请重试。' : '请登录后继续。'); }
    const json = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof json.detail === 'string' ? json.detail : `请求失败（${response.status}）`);
    return json;
  }
  async function action(button, operation, errorId) { button.disabled = true; if (errorId) $(errorId).textContent = ''; try { await operation(); } catch (error) { if (errorId) $(errorId).textContent = error.message; else notify(error.message, true); } finally { button.disabled = false; } }
  function range(from = $('from-date').value, to = $('to-date').value) { if (!from || !to || from > to) throw new Error('请选择有效日期，开始日期不能晚于结束日期。'); return new URLSearchParams({ from_date: from, to_date: to }).toString(); }
  function aggregate(days, key, operation = 'average') { const values = days.map(d => d.summary?.[key]).filter(v => v != null && Number.isFinite(Number(v))).map(Number); if (!values.length) return null; const sum = values.reduce((a, b) => a + b, 0); return operation === 'sum' ? sum : sum / values.length; }
  function renderMetrics(days) {
    const metrics = [ ['总步数', 'steps', '步', 'sum'], ['活动距离', 'distance_meters', 'km', 'sum', 1000], ['消耗热量', 'calories', 'kcal', 'sum'], ['平均睡眠', 'sleep_minutes', '小时', 'average', 60], ['静息心率', 'resting_hr', 'bpm'], ['平均睡眠评分', 'sleep_score', '分'] ];
    $('metrics').innerHTML = metrics.map(([label, key, unit, op, divisor = 1]) => { const value = aggregate(days, key, op); const count = days.filter(d => d.summary?.[key] != null).length; return `<article class="metric"><div class="metric-label">${label}</div><div class="metric-value">${number(value == null ? null : value / divisor, divisor > 1 ? 1 : 0)}<small>${unit}</small></div><div class="metric-note">${count ? `${count} 天有记录 · ${op === 'sum' ? '区间合计' : '有记录日均值'}` : '暂无记录'}</div></article>`; }).join('');
  }
  function lineChart(id, samples, color, label) {
    const points = samples.filter(p => p.time != null && p.value != null && Number.isFinite(Number(p.time)) && Number.isFinite(Number(p.value))).map(p => ({ time: Number(p.time), value: Number(p.value) })).sort((a, b) => a.time - b.time);
    if (!points.length) { $(id).innerHTML = '<div class="empty">所选日期暂无采样记录</div>'; return; }
    const width = 620, height = 240, left = 40, right = 15, top = 18, bottom = 38;
    const start = points[0].time, end = Math.max(start + 60000, points[points.length - 1].time);
    let min = Infinity, max = -Infinity; for (const p of points) { min = Math.min(min, p.value); max = Math.max(max, p.value); }
    const padding = Math.max((max - min) * .15, 5); min = Math.max(0, Math.floor(min - padding)); max = Math.ceil(max + padding);
    const x = t => left + (t - start) / (end - start) * (width - left - right), y = v => top + (max - v) / (max - min) * (height - top - bottom);
    // Preserve segment boundaries before pixel sampling. Keep first/last and extrema
    // in each pixel bucket so dense ranges remain small without hiding spikes.
    const drawn = []; let bucket = [], bucketPixel = -1, segmentStart = true;
    function flushBucket() {
      if (!bucket.length) return;
      let low = 0, high = 0;
      for (let i = 1; i < bucket.length; i++) { if (bucket[i].value < bucket[low].value) low = i; if (bucket[i].value > bucket[high].value) high = i; }
      for (const i of [...new Set([0, low, high, bucket.length - 1])].sort((a, b) => a - b)) { drawn.push({ ...bucket[i], move: segmentStart }); segmentStart = false; }
      bucket = [];
    }
    points.forEach((p, i) => {
      const gap = i > 0 && p.time - points[i - 1].time > 15 * 60000;
      const pixel = Math.floor(x(p.time));
      if (gap || pixel !== bucketPixel) flushBucket();
      if (gap) segmentStart = true;
      bucketPixel = pixel; bucket.push(p);
    }); flushBucket();
    let lines = '', dots = '';
    drawn.forEach((p, i) => {
      lines += `${p.move ? 'M' : 'L'}${x(p.time).toFixed(1)},${y(p.value).toFixed(1)} `;
      if (p.move && (i === drawn.length - 1 || drawn[i + 1].move)) dots += `M${x(p.time).toFixed(1)},${y(p.value).toFixed(1)}h.1 `;
    });
    dots = dots ? `<path d="${dots}" fill="none" stroke="${color}" stroke-width="4" stroke-linecap="round"/>` : '';

    let grid = ''; for (let i = 0; i < 4; i++) { const v = min + (max - min) * i / 3; grid += `<line x1="${left}" y1="${y(v)}" x2="${width - right}" y2="${y(v)}" stroke="#293b46"/><text x="${left - 9}" y="${y(v) + 4}" text-anchor="end" fill="#a0b3bd" font-size="12">${Math.round(v)}</text>`; }
    $(id).innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${label}：${points.length} 个采样点，时间范围 ${escape(formatTime(start))} 至 ${escape(formatTime(end))}"><title>${label}趋势；数据间隔超过 15 分钟处断开</title>${grid}<path d="${lines}" fill="none" stroke="${color}" stroke-width="1.7" stroke-linejoin="round"/>${dots}<text x="${left}" y="${height - 10}" fill="#a0b3bd" font-size="12">${escape(formatTime(start))}</text><text x="${width - right}" y="${height - 10}" text-anchor="end" fill="#a0b3bd" font-size="12">${escape(formatTime(end))}</text></svg>`;
  }
  function renderSleep(days) {
    const rows = days.filter(d => d.sleep_stages?.length || d.summary?.sleep_minutes != null || d.summary?.sleep_score != null);
    if (!rows.length) { $('sleep-chart').innerHTML = '<div class="empty">所选日期暂无睡眠记录</div>'; return; }
    const names = { deep: '深睡', light: '浅睡', rem: 'REM', awake: '清醒', unknown: '未知' };
    $('sleep-chart').innerHTML = rows.map(day => {
      const stages = (day.sleep_stages || []).filter(s => Number.isFinite(Number(s.start)) && Number.isFinite(Number(s.end)) && Number(s.end) > Number(s.start));
      let blocks = '<span class="muted small">暂无阶段记录</span>';
      if (stages.length) { const start = Math.min(...stages.map(s => Number(s.start))), end = Math.max(...stages.map(s => Number(s.end))); blocks = `<div class="sleep-track" role="img" aria-label="${escape(day.date)}睡眠阶段，共 ${stages.length} 段">${stages.map(s => { const stage = Object.hasOwn(names, String(s.stage).toLowerCase()) ? String(s.stage).toLowerCase() : 'unknown'; return `<span class="sleep-block ${stage}" style="left:${(s.start - start) / (end - start) * 100}%;width:${(s.end - s.start) / (end - start) * 100}%" title="${names[stage]} ${escape(formatTime(s.start))}–${escape(formatTime(s.end))}"></span>`; }).join('')}</div><div class="sleep-times"><span>${escape(formatTime(start))}</span><span>${escape(formatTime(end))}</span></div>`; }
      const durations = [['deep', '深睡'], ['light', '浅睡'], ['rem', 'REM'], ['awake', '清醒']].filter(([key]) => day.summary?.[`sleep_${key}_minutes`] != null).map(([key, label]) => `${label} ${number(day.summary[`sleep_${key}_minutes`])} 分钟`).join(' · ');
      return `<div class="sleep-row"><div class="sleep-label"><span>${escape(day.date)}</span><span>${number(day.summary?.sleep_minutes)} 分钟 · 评分 ${number(day.summary?.sleep_score)}</span></div>${blocks}${durations ? `<p class="chart-note">${durations}</p>` : ''}</div>`;
    }).join('');
  }
  function renderData(data) {
    state.timezone = data.timezone || state.timezone;
    const days = (data.days || []).slice().sort((a, b) => a.date.localeCompare(b.date));
    renderMetrics(days); lineChart('heart-chart', days.flatMap(d => d.heart_rate || []), '#66dfc1', '心率'); lineChart('stress-chart', days.flatMap(d => d.stress || []), '#e3bf80', '压力'); renderSleep(days);
    const keys = ['steps', 'trimp', 'atl', 'ctl', 'tsb', 'sport_load', 'weekly_load', 'vo2_max'];
    $('training-body').innerHTML = days.length ? days.map(d => `<tr><td>${escape(d.date)}</td>${keys.map(k => `<td>${number(d.summary?.[k], k === 'steps' ? 0 : 1)}</td>`).join('')}</tr>`).join('') : '<tr><td colspan="9">所选日期暂无活动记录</td></tr>';
    $('data-state').textContent = days.length ? '' : '暂无归档数据。配置账号后点击“立即同步”，或选择其他日期。';
    $('period-caption').textContent = `${$('from-date').value} — ${$('to-date').value} · ${days.length} 天有归档`;
    $('timezone-label').textContent = state.timezone;
  }
  async function loadData() {
    const query = range(); const request = ++state.dataRequest, session = state.session;
    $('data-state').textContent = '正在读取健康档案…'; $('export').href = `/api/export?${query}`;
    try { const data = await api(`/api/data?${query}`); if (request === state.dataRequest && session === state.session) renderData(data); } catch (error) { if (request === state.dataRequest && session === state.session) { $('data-state').textContent = `读取失败：${error.message}`; throw error; } }
  }
  function renderStatus(status) {
    $('setup-banner').hidden = !!status.configured;
    const label = !status.configured ? '等待配置' : status.auth_required ? 'Token 需要更新' : !status.worker_alive ? '同步服务离线' : status.tasks?.running ? '正在同步' : '同步服务在线';
    $('connection').textContent = label; $('connection').classList.toggle('warning', !status.configured || status.auth_required || !status.worker_alive);
    const timestamp = value => value ? formatTime(value * 1000) : '—';
    const stats = [['最近成功', timestamp(status.last_success)], ['下次同步', timestamp(status.next_sync)], ['任务进度', `${status.tasks?.done ?? 0} 完成 · ${status.tasks?.running ?? 0} 运行 · ${status.tasks?.pending ?? 0} 等待 · ${status.tasks?.failed ?? 0} 失败`], ['VM 待发送 / 冲突', `${status.pending_exports ?? 0} / ${status.conflicts ?? 0}`]];
    $('retry-failed').disabled = !(status.tasks?.failed > 0);
    $('sync-stats').innerHTML = stats.map(([name, value]) => `<div class="sync-stat"><span>${name}</span><strong>${escape(value)}</strong></div>`).join('');
    $('sync-error').textContent = [status.auth_required ? 'Zepp 授权已失效，请在设置中更新 Token。' : '', status.worker_error ? `同步服务：${status.worker_error}` : '', status.vm_error ? `VictoriaMetrics：${status.vm_error}` : '', status.conflicts ? '存在历史指标修订冲突。可选择对应日期导出 JSONL，按部署文档在新的 VictoriaMetrics 租户重建数据。' : ''].filter(Boolean).join(' ');
    const labels = { pending: '等待中', running: '同步中', failed: '失败', done: '已完成', band: '心率/睡眠/活动', trimp: 'TRIMP', sport: '运动负荷', vo2: 'VO₂ Max', daily: '日汇总', heart_rate: '心率', stress: '压力', sleep: '睡眠', activity: '活动', training: '训练' };
    $('tasks-body').innerHTML = status.recent_tasks?.length ? status.recent_tasks.map(t => `<tr><td>${escape(t.day)}</td><td>${escape(labels[t.kind] || t.kind)}</td><td>${escape(labels[t.status] || t.status)}</td><td>${escape(timestamp(t.updated_at))}</td><td>${escape(t.error || '—')}</td></tr>`).join('') : '<tr><td colspan="5">暂无同步任务</td></tr>';
  }
  async function pollStatus() {
    if (!state.active || state.statusBusy) return;
    state.statusBusy = true; const session = state.session;
    try { const status = await api('/api/status'); if (session !== state.session) return; renderStatus(status); const fingerprint = JSON.stringify([status.last_success, status.tasks?.done]); if (state.fingerprint && fingerprint !== state.fingerprint) await loadData(); state.fingerprint = fingerprint; } catch (error) { if (state.active && session === state.session) { $('connection').textContent = '连接中断'; $('connection').classList.add('warning'); $('sync-error').textContent = error.message; } } finally { state.statusBusy = false; clearTimeout(state.timer); if (state.active) state.timer = setTimeout(pollStatus, 10000); }
  }
  function fillSettings(settings) {
    state.settings = settings; const form = $('settings-form');
    for (const name of ['user_id', 'region', 'timezone', 'interval_minutes', 'initial_days', 'lookback_days']) form.elements[name].value = settings[name] ?? ({ region: 'global', timezone: 'Asia/Shanghai', interval_minutes: 30, initial_days: 30, lookback_days: 3 }[name] ?? '');
    form.elements.token.value = ''; $('token-status').textContent = settings.token_configured ? '已配置 Token；填写新值将替换现有凭据。' : '尚未配置 Token。';
    $('account-info').textContent = `账号标识：${settings.account || '未设置'}`; $('vm-info').textContent = `VictoriaMetrics：${settings.vm_url || '未配置'}`;
  }
  async function start() {
    const settings = await api('/api/settings'); fillSettings(settings); state.timezone = settings.timezone || 'Asia/Shanghai'; state.active = true; state.session++; state.fingerprint = '';
    $('login-view').hidden = true; $('app-view').hidden = false; setWeek(); await Promise.all([loadData(), pollStatus()]);
  }
  $('login-form').addEventListener('submit', e => { e.preventDefault(); action(e.submitter, async () => { await api('/api/login', 'POST', { password: e.target.elements.password.value }); e.target.reset(); await start(); }, 'login-error'); });
  $('logout').addEventListener('click', e => action(e.currentTarget, async () => { await api('/api/logout', 'POST', {}); loggedOut(); }));
  $('range-form').addEventListener('submit', e => { e.preventDefault(); action(e.submitter, loadData); });
  $('week-range').addEventListener('click', e => action(e.currentTarget, async () => { setWeek(); await loadData(); }));
  $('refresh').addEventListener('click', e => action(e.currentTarget, async () => { await Promise.all([loadData(), pollStatus()]); }));
  $('retry-failed').addEventListener('click', e => action(e.currentTarget, async () => { const result = await api('/api/retry', 'POST', {}); notify(`已重新加入队列：${result.queued ?? 0} 个失败任务`); await pollStatus(); }));
  $('sync-now').addEventListener('click', e => action(e.currentTarget, async () => { const result = await api('/api/sync', 'POST', {}); notify(`已加入同步队列：${result.queued ?? 0} 个任务`); await pollStatus(); }));
  for (const id of ['settings-open', 'setup-open']) $(id).addEventListener('click', e => action(e.currentTarget, async () => { fillSettings(await api('/api/settings')); $('settings-error').textContent = ''; $('settings-dialog').showModal(); }));
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $(button.dataset.close).close()));
  $('settings-form').addEventListener('submit', e => { e.preventDefault(); action(e.submitter, async () => { const fields = Object.fromEntries(new FormData(e.target)); for (const key of ['interval_minutes', 'initial_days', 'lookback_days']) fields[key] = Number(fields[key]); await api('/api/settings', 'PUT', fields); fillSettings(await api('/api/settings')); state.timezone = state.settings.timezone; $('settings-dialog').close(); notify('设置已保存'); await Promise.all([loadData(), pollStatus()]); }, 'settings-error'); });
  $('backfill-open').addEventListener('click', () => { const form = $('backfill-form'); form.elements.from_date.value = $('from-date').value; form.elements.to_date.value = $('to-date').value; form.elements.force.checked = false; $('backfill-error').textContent = ''; $('backfill-dialog').showModal(); });
  $('backfill-form').addEventListener('submit', e => { e.preventDefault(); action(e.submitter, async () => { const fields = Object.fromEntries(new FormData(e.target)); fields.force = e.target.elements.force.checked; range(fields.from_date, fields.to_date); const result = await api('/api/sync', 'POST', fields); $('backfill-dialog').close(); notify(`已加入同步队列：${result.queued ?? 0} 个任务`); await pollStatus(); }, 'backfill-error'); });
  start().catch(error => { if (!state.active) { loggedOut(); if (error.message !== '请登录后继续。') $('login-error').textContent = error.message; } else notify(error.message, true); });
})();
