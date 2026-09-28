import "./style.css";
import { $, state, restore, persist, query, notice, escape, today } from "./state.js";
import { api, action } from "./api.js";
import { rangePicker } from "./range-picker.js";
import { renderTrends, resize } from "./trend-charts.js";
import { setupDay, loadProfile, showDay, clearDayCache } from "./day-inspector.js";
import { setupCoverage, loadCoverage } from "./sync-calendar.js";
let data = null, request = 0, timer, busy = false, fingerprint = "", settings, latestStatus=null, scheduleTimer, previousNav=null;
const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
motionPreference.addEventListener('change',event=>{
  if(event.matches)document.getAnimations().forEach(animation=>animation.cancel());
});
function logout() {
  clearDayCache();
  state.active = false;
  request++;
  clearTimeout(timer);
  clearInterval(scheduleTimer);
  document.querySelectorAll("dialog[open]").forEach((d) => d.close());
  $("app-view").hidden = true;
  $("login-view").hidden = false;
}
window.addEventListener("session-expired", logout);
window.addEventListener("app-error", (e) => notice(e.detail, true));
function nav() {
  document.querySelectorAll("[data-nav]").forEach((b) => b.setAttribute("aria-current", b.dataset.nav === state.nav ? "page" : "false"));
  $("trends-view").hidden = state.nav !== "trends";
  $("sync-view").hidden = state.nav !== "sync";
  if(previousNav!==state.nav && !matchMedia('(prefers-reduced-motion: reduce)').matches){
    $(state.nav==='sync'?'sync-view':'trends-view').animate([{opacity:.35,transform:'translateY(10px)'},{opacity:1,transform:'translateY(0)'}],{duration:320,easing:'cubic-bezier(.2,.7,.2,1)'});
  }
  previousNav=state.nav;
  requestAnimationFrame(resize);
}
async function load() {
  const id = ++request;
  $("range-open").textContent = state.from + " — " + state.to;
  $("period-caption").textContent = `${state.from} — ${state.to} · ${state.timezone}${state.to === today(state.timezone) ? " · 今天的数据仍在更新" : " · 完整日期区间"}`;
  $("compare").value = state.compare;
  $("grain").value = state.grain;
  $("export").href = "/api/export?" + query();
  nav();
  $("data-state").textContent = "正在读取档案…";
  try {
    if (state.nav === "sync") {
      await loadCoverage();
      if (id === request) $("data-state").textContent = "";
      return;
    }
    const p = query();
    p.set("compare", state.compare);
    p.set("grain", state.grain);
    const d = await api("/api/analytics/trends?" + p);
    if (id !== request || !state.active) return;
    data = d;
    renderTrends(data, openDay);
    $("comparison-note").textContent = d.comparison ? `比较区间：${d.comparison.from_date} — ${d.comparison.to_date} · 缺失日期不计为零；不足覆盖仅供参考。` : "未选择对比或历史不足。可在同步日历中补齐历史。";
    if (d.summary_range) $("comparison-note").textContent += ` 当前统计有效范围：${d.summary_range.from_date} — ${d.summary_range.to_date}${d.summary_excludes_today ? "（不含尚未结束的今天）" : ""}。`;
    else if (d.summary_excludes_today) $("comparison-note").textContent += " 当前范围只有今天，日汇总比较等待今天结束；下方曲线仍显示已观测数据。";
    if (state.grain !== "day") $("comparison-note").textContent += " 周/月心率、压力与血氧按每日中位数汇总；并非全周期逐分钟分布。";
    if (d.quality === "index_pending") $("comparison-note").textContent += " 分析索引正在重建，部分日期暂未就绪。";
    $("data-state").textContent = (d.days || []).some((day) => Object.keys(day.summary || {}).length || day.heart_rate?.n || day.stress?.n || day.spo2?.n) ? "" : "所选范围暂无记录。可前往同步日历补齐历史。";
    await loadProfile();
  } catch (e) {
    if (id === request) $("data-state").textContent = "读取失败：" + e.message;
    throw e;
  }
}
function openDay(day) {
  day = day < state.from ? state.from : day > state.to ? state.to : day;
  state.day = day;
  persist();
  showDay(day).catch((e) => notice(e.message, true));
  $("profile-chart").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "center" });
}
function renderSyncSchedule() {
  if(!settings)return;
  const interval=settings.interval_minutes,lookback=settings.lookback_days;
  $('sync-cadence').textContent=`每 ${interval??'—'} 分钟 · 回看 ${lookback??'—'} 天`;
  const s=latestStatus;if(!s)return;
  const format=seconds=>new Intl.DateTimeFormat('zh-CN',{timeZone:state.timezone,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(seconds*1000));
  $('sync-last').textContent=s.last_success?format(s.last_success):'暂无成功记录';
  let next='等待调度';
  if(!s.configured)next='配置账号后开始';
  else if(s.auth_required)next='授权待更新 · 已暂停';
  else if(!s.worker_alive)next='同步服务离线';
  else if(s.next_sync){
    const seconds=Math.max(0,Math.ceil(s.next_sync-Date.now()/1000));
    const countdown=seconds>=60?`约 ${Math.ceil(seconds/60)} 分钟后`:seconds>0?`${seconds} 秒后`:'即将执行';
    next=`${format(s.next_sync)} · ${countdown}`;
  }
  $('sync-next').textContent=next;
  $('sync-next').title=`计划时间，显示时区：${state.timezone}。排队与失败重试可能影响实际执行时间。`;
  document.querySelector('.live-dot').classList.toggle('paused',!!s.auth_required||!s.worker_alive||!s.configured);
}
function startScheduleClock(){
  clearInterval(scheduleTimer);
  if(state.active&&!document.hidden)scheduleTimer=setInterval(renderSyncSchedule,1000);
}
function fill(s) {
  settings = s;
  renderSyncSchedule();
  const f = $("settings-form");
  for (const name of ["user_id", "region", "timezone", "interval_minutes", "initial_days", "lookback_days"]) f.elements[name].value = s[name] ?? ({ region: "global", timezone: "Asia/Shanghai", interval_minutes: 30, initial_days: 30, lookback_days: 3 }[name] || "");
  f.elements.token.value = "";
  $("token-status").textContent = s.token_configured ? "已配置；留空保留当前 Token。" : "尚未配置 Token。";
  $("account-info").textContent = "账号标识：" + (s.account || "未设置");
  $("vm-info").textContent = "VictoriaMetrics：" + (s.vm_url || "未配置");
}
async function poll() {
  if (!state.active || busy || document.hidden) return;
  busy = true;
  let running = false;
  try {
    const s = await api("/api/status");
    if (!state.active) return;
    latestStatus=s;renderSyncSchedule();
    running = !!(s.tasks?.running || s.tasks?.pending);
    $("connection").textContent = s.auth_required ? "授权待更新" : !s.configured ? "等待配置" : s.worker_alive ? "● 同步在线" : "服务离线";
    $("setup-banner").hidden = !!s.configured && !s.auth_required;
    $("setup-banner").firstChild.textContent = s.auth_required ? "Zepp 授权需要更新。队列已暂停，更新后继续。" : "连接 Zepp 账号，开始建立健康档案。";
    $("sync-freshness").textContent = "最近成功归档：" + (s.last_success ? new Intl.DateTimeFormat("zh-CN", { timeZone: state.timezone, dateStyle: "medium", timeStyle: "short" }).format(new Date(s.last_success * 1e3)) : "暂无成功记录");
    $("sync-error").textContent = [s.auth_required ? "Zepp 授权已失效；请在设置中更新 Token，队列将继续。" : "", s.worker_error, s.vm_error].filter(Boolean).join(" ");
    $("sync-stats").innerHTML = [["已完成", s.tasks?.done || 0], ["执行中", s.tasks?.running || 0], ["等待", s.tasks?.pending || 0], ["失败", s.tasks?.failed || 0], ["待投递", s.pending_exports || 0], ["分析索引", `${s.analytics?.ready ?? 0} 就绪 / ${s.analytics?.pending ?? 0} 等待`]].map(([k, v]) => `<div><span>${k}</span><strong>${escape(v)}</strong></div>`).join("");
    $("index-state").textContent = s.analytics?.pending || s.analytics?.failed ? `分析索引：${s.analytics?.pending || 0} 天等待重建，${s.analytics?.failed || 0} 天重建失败（自动重试）。归档数据仍保留。` : "";
    const next = JSON.stringify([s.last_success, s.tasks?.done, s.analytics]);
    if (fingerprint && next !== fingerprint) {
      clearDayCache();
      if (state.nav === "trends") await load();
    }
    fingerprint = next;
    if (state.nav === "sync") await loadCoverage();
  } catch (e) {
    if (state.active) {
      $("connection").textContent = "连接中断";
      $("sync-error").textContent = e.message;
    }
  } finally {
    busy = false;
    clearTimeout(timer);
    if (state.active) timer = setTimeout(poll, running ? 3e3 : 15e3);
  }
}
async function start() {
  const s = await api("/api/settings");
  fill(s);
  state.timezone = s.timezone || "Asia/Shanghai";
  restore();
  state.active = true;
  startScheduleClock();
  $("login-view").hidden = true;
  $("app-view").hidden = false;
  $("timezone-label").textContent = state.timezone;
  await Promise.all([load(), poll()]);
}
rangePicker(() => action(null, load));
setupDay();
setupCoverage();
document.querySelectorAll("[data-nav]").forEach((b) => b.onclick = () => {
  state.nav = b.dataset.nav;
  persist();
  action(b, load);
});
$("compare").onchange = (e) => {
  state.compare = e.target.value;
  persist();
  action(null, load);
};
$("grain").onchange = (e) => {
  state.grain = e.target.value;
  persist();
  action(null, load);
};
for (const id of ["statistic", "band", "training-metric", "sleep-metric", "activity-source"]) $(id).onchange = () => {
  if (data) renderTrends(data, openDay);
  action(null, loadProfile);
};
window.onpopstate = () => {
  restore();
  action(null, load);
};
$("refresh").onclick = (e) => action(e.currentTarget, async () => {
  clearDayCache();
  await Promise.all([load(), poll()]);
});
$("sync-now").onclick = (e) => action(e.currentTarget, async () => {
  const r = await api("/api/sync", "POST", {});
  notice(`已加入持久队列：${r.queued || 0} 项`);
  await poll();
});
for (const id of ["settings-open", "setup-open"]) $(id).onclick = (e) => action(e.currentTarget, async () => {
  fill(await api("/api/settings"));
  $("settings-dialog").showModal();
});
document.querySelectorAll("[data-close]").forEach((b) => b.onclick = () => $(b.dataset.close).close());
$("settings-form").onsubmit = (e) => {
  e.preventDefault();
  action(e.submitter, async () => {
    const fields = Object.fromEntries(new FormData(e.target));
    for (const k of ["interval_minutes", "initial_days", "lookback_days"]) fields[k] = Number(fields[k]);
    await api("/api/settings", "PUT", fields);
    fill(await api("/api/settings"));
    state.timezone = settings.timezone;
    $("settings-dialog").close();
    notice("设置已保存");
    await load();
  });
};
$("login-form").onsubmit = (e) => {
  e.preventDefault();
  action(e.submitter, async () => {
    await api("/api/login", "POST", { password: e.target.elements.password.value });
    e.target.reset();
    await start();
  });
};
$("logout").onclick = (e) => action(e.currentTarget, async () => {
  await api("/api/logout", "POST", {});
  logout();
});
document.addEventListener("visibilitychange", () => {
  clearTimeout(timer);
  startScheduleClock();
  if (!document.hidden) poll();
});
start().catch((e) => {
  if (state.active) notice(e.message, true);
  else logout();
});
window.addEventListener("selection-trends", () => action(null, load));
