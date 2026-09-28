import { api } from "./api.js";
import { $, state, query, addDays, persist, escape, number } from "./state.js";
import { plot, bands } from "./trend-charts.js";
import { clampDay, createDayCache } from "./frontend-utils.js";
const dayCache = createDayCache((day) => api("/api/days/" + day));
let baseline = [], request = 0, baselineRequest = 0, timer;
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
function sleepTimeline(stages) {
  if (!stages?.length) return '<p class="muted small">暂无睡眠阶段记录。</p>';
  const start = Math.min(...stages.map((s) => s.start)), end = Math.max(...stages.map((s) => s.end));
  const format = (ms) => new Intl.DateTimeFormat("zh-CN", { timeZone: state.timezone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(ms));
  return '<div class="sleep-stages" role="img" aria-label="睡眠阶段时间线，留白表示未识别区间">' + stages.map((s) => {
    const label = { deep: "深睡", light: "浅睡", rem: "REM", awake: "清醒" }[s.stage] || "未知";
    return `<span class="stage ${escape(s.stage)}" title="${label} ${format(s.start)}–${format(s.end)}" style="left:${(s.start - start) / (end - start) * 100}%;width:${(s.end - s.start) / (end - start) * 100}%">${label}</span>`;
  }).join("") + `</div><p class="small muted">${format(start)} — ${format(end)} · 留白表示未识别区间</p>`;
}
async function showDay(day) {
  day = clampDay(day, state.from, state.to);
  state.day = day;
  $("overlay-day").value = day;
  $("overlay-day").min = state.from;
  $("overlay-day").max = state.to;
  $("day-slider").max = Math.round((Date.parse(state.to) - Date.parse(state.from)) / 864e5);
  $("day-slider").value = Math.round((Date.parse(day) - Date.parse(state.from)) / 864e5);
  const id = ++request;
  const detail = await getDay(day);
  if (id !== request || !state.active) return;
  for (const neighbor of [addDays(day, -1), addDays(day, 1)]) if (neighbor >= state.from && neighbor <= state.to) getDay(neighbor).catch(() => {
  });
  const metric = $("profile-metric").value;
  const points = detail.profiles?.[metric] || [];
  const map = new Map(points.map((p) => [p.minute, p.value]));
  const rows = baseline.map((b) => ({ ...b, p25: b.n >= 5 ? b.p25 : null, p75: b.n >= 5 ? b.p75 : null, p10: b.n >= 5 ? b.p10 : null, p90: b.n >= 5 ? b.p90 : null, p50: b.n >= 2 ? b.p50 : null, mean: b.n >= 2 ? b.mean : null }));
  plot("profile-chart", rows.map((r) => clock(r.minute)), [...bands(rows, null, $("statistic").value, $("band").value === "outer"), { name: day, type: "line", data: rows.map((r) => map.get(r.minute) ?? null), itemStyle: { color: "#e1b676" }, lineStyle: { width: 2 } }], null, { tooltip: { trigger: "axis", confine: true, formatter: (params) => {
    const i = params[0]?.dataIndex, b = rows[i];
    if (!b) return "";
    return `${clock(b.minute)} · 基于 ${b.n} 天<br>中位数 ${number(b.p50, 1)}<br>P25–P75 ${number(b.p25, 1)}–${number(b.p75, 1)}<br>${day} ${number(map.get(b.minute), 1)}`;
  } } });
  const coverage = Object.entries(detail.coverage || {}).map(([key, c]) => `${key === "heart_rate" ? "心率" : "压力"}：观测 ${number(c.observed_minutes)} / ${number(c.expected_minutes)} 分钟，${number(c.n)} 个样本`).join(" · ");
  const sleepQuality = `睡眠阶段覆盖 ${number(detail.summary?.sleep_stage_coverage == null ? null : detail.summary.sleep_stage_coverage * 100, 1)}% · 未识别 ${number(detail.summary?.sleep_gap_minutes, 1)} 分钟 · 重叠 ${number(detail.summary?.sleep_overlap_minutes, 1)} 分钟`;
  $("day-detail").innerHTML = `<h3>${escape(day)} <span class="muted">· 单日记录</span></h3><p>步数 ${number(detail.summary?.steps)} · 可识别睡眠 ${number(detail.summary?.actual_sleep_minutes)} 分钟 · 活动片段 ${detail.activities?.length || 0} 段</p><p class="small muted">${escape(coverage)}</p><p class="small muted">${escape(sleepQuality)}</p>` + sleepTimeline(detail.sleep_stages) + (detail.activities || []).slice(0, 20).map((a) => `<p class="small">${escape(a.label || a.type || "未知活动")} · ${number(a.minutes ?? a.duration_minutes, 1)} 分钟</p>`).join("") + "<h3>完整运动记录</h3>" + ((detail.workouts || []).length ? (detail.workouts || []).map((w) => `<p class="small">${escape({ outdoor_running: "户外跑步", walking: "步行", outdoor_cycling: "户外骑行", pool_swimming: "泳池游泳", football: "足球", rope_skipping: "跳绳", hiking: "徒步", strength_training: "力量训练" }[w.type] || w.type)} · ${number(w.minutes, 1)} 分钟 · ${number(w.distance_meters == null ? null : w.distance_meters / 1e3, 2)} km</p>`).join("") : '<p class="muted small">暂无完整运动记录。</p>');
}
function clearDayCache() {
  dayCache.clear();
  request++;
  baselineRequest++;
}
function setupDay() {
  const choose = (d) => {
    showDay(d).catch((e) => window.dispatchEvent(new CustomEvent("app-error", { detail: e.message })));
    persist();
  };
  $("overlay-day").onchange = (e) => choose(e.target.value);
  $("day-prev").onclick = () => choose(addDays(state.day, -1));
  $("day-next").onclick = () => choose(addDays(state.day, 1));
  $("day-slider").oninput = (e) => {
    clearTimeout(timer);
    const d = addDays(state.from, +e.target.value);
    $("overlay-day").value = d;
    timer = setTimeout(() => choose(d), 150);
  };
  $("profile-metric").onchange = () => loadProfile().catch((e) => window.dispatchEvent(new CustomEvent("app-error", { detail: e.message })));
}
export {
  clearDayCache,
  loadProfile,
  setupDay,
  showDay
};
