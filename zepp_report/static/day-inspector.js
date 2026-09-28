import {renderSleepNight} from "./sleep-night.js";
import {renderRawDay} from "./raw-day.js";
import { api } from "./api.js";
import { $, state, query, addDays, persist, escape, number } from "./state.js";
import { plot, bands } from "./trend-charts.js";
import { clampDay, createDayCache } from "./frontend-utils.js";
const dayCache = createDayCache((day) => api("/api/days/" + day));
let baseline = [], request = 0, baselineRequest = 0;
const clock = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
async function loadProfile() {
  const id = ++baselineRequest, metric = $("profile-metric").value;
  const p = new URLSearchParams(query());
  p.set("metric", metric);
  const result = await api("/api/analytics/profile?" + p);
  if (id !== baselineRequest || !state.active) return;
  baseline = result.buckets || [];
  await showDay(state.day);
}
const getDay = (day) => dayCache.get(day);
function syncDayControls(day){
  $('overlay-day').value=day;$('overlay-day').min=state.from;$('overlay-day').max=state.to;
  $('day-prev').disabled=day===state.from;
  $('day-next').disabled=day===state.to;
  const total=Math.round((Date.parse(state.to)-Date.parse(state.from))/86400000)+1;
  const offset=Math.round((Date.parse(day)-Date.parse(state.from))/86400000);
  const start=Math.max(0,Math.min(offset-2,total-5));
  const dates=Array.from({length:Math.min(5,total)},(_,i)=>addDays(state.from,start+i));
  const key=dates.join(',');
  if($('day-dates').dataset.window!==key){
    $('day-dates').dataset.window=key;
    $('day-dates').innerHTML=dates.map(date=>{
      const week=new Intl.DateTimeFormat('zh-CN',{weekday:'short',timeZone:'UTC'}).format(new Date(date+'T12:00:00Z'));
      return `<button type="button" data-day="${date}" aria-label="查看 ${date} ${week}"><span>${week}</span><strong>${Number(date.slice(8))}</strong><small>${Number(date.slice(5,7))} 月</small></button>`;
    }).join('');
  }
  for(const button of $('day-dates').children)button.setAttribute('aria-pressed',String(button.dataset.day===day));

}
async function showDay(day) {
  day = clampDay(day,state.from,state.to);
  state.day=day;syncDayControls(day);
  $('day-preview').textContent=`正在读取 ${day}…`;
  const id = ++request;
  let detail;
  try { detail=await getDay(day); }
  catch(error){
    if(id!==request||!state.active)return;
    $('day-preview').textContent=`${day} 读取失败，请重试。`;
    throw error;
  }
  if (id !== request || !state.active) return;
  for (const neighbor of [addDays(day, -1), addDays(day, 1)]) if (neighbor >= state.from && neighbor <= state.to) getDay(neighbor).catch(() => {
  });
  const metric = $("profile-metric").value;
  const points = detail.profiles?.[metric] || [];
  const unit=metric==="spo2"?"%":metric==="heart_rate"?" bpm":"";
  const map = new Map(points.map((p) => [p.minute, p.value]));
  const rows = baseline.map((b) => ({ ...b, p25: b.n >= 5 ? b.p25 : null, p75: b.n >= 5 ? b.p75 : null, p10: b.n >= 5 ? b.p10 : null, p90: b.n >= 5 ? b.p90 : null, p50: b.n >= 2 ? b.p50 : null, mean: b.n >= 2 ? b.mean : null }));
  plot("profile-chart", rows.map((r) => clock(r.minute)), [...bands(rows, null, $("statistic").value, $("band").value === "outer"), { name: day, type: "line", data: rows.map((r) => map.get(r.minute) ?? null), itemStyle: { color: "#e1b676" }, lineStyle: { width: 2 } }], null, { tooltip: { trigger: "axis", confine: true, formatter: (params) => {
    const i = params[0]?.dataIndex, b = rows[i];
    if (!b) return "";
    return `${clock(b.minute)} · 基于 ${b.n} 天<br>中位数 ${number(b.p50, 1)}${unit}<br>P25–P75 ${number(b.p25, 1)}–${number(b.p75, 1)}${unit}<br>${day} ${number(map.get(b.minute), 1)}${unit}`;
  } } });
  const coverage = Object.entries(detail.coverage || {}).map(([key, c]) => `${({heart_rate:"心率",stress:"压力",spo2:"血氧"})[key]||key}：观测 ${number(c.observed_minutes)} / ${number(c.expected_minutes)} 分钟，${number(c.n)} 个样本`).join(" · ");
  $('day-detail').innerHTML=`<h3>${escape(day)} <span class="muted">· 单日记录</span></h3><p>步数 ${number(detail.summary?.steps)} · 活动片段 ${detail.activities?.length||0} 段</p><p class="small muted">${escape(coverage)}</p><section id="sleep-night" class="sleep-night"></section>`;
  renderSleepNight(detail);
  $('day-preview').textContent=`已显示 ${day} · 点击日期即可切换`;
  renderRawDay(detail);
}
function clearDayCache() {
  dayCache.clear();
  request++;
  baselineRequest++;
}
function setupDay() {
  const choose=(day)=>{
    showDay(day).catch(e=>window.dispatchEvent(new CustomEvent('app-error',{detail:e.message})));
    persist();
  };
  $('overlay-day').onchange=e=>{if(e.target.value)choose(e.target.value)};
  $('day-prev').onclick=()=>choose(addDays(state.day,-1));
  $('day-next').onclick=()=>choose(addDays(state.day,1));
  $('day-dates').onclick=e=>{
    const button=e.target.closest('button[data-day]');
    if(button){
      choose(button.dataset.day);
      $('day-dates').querySelector('[aria-pressed="true"]')?.focus({preventScroll:true});
    }
  };
  $("profile-metric").onchange = () => loadProfile().catch((e) => window.dispatchEvent(new CustomEvent("app-error", { detail: e.message })));
}
export {
  clearDayCache,
  loadProfile,
  setupDay,
  showDay
};
