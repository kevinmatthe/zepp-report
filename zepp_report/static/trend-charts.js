import {renderMetrics} from "./metric-cards.js";
import * as echarts from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, AriaComponent, GraphicComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { $, number, escape } from "./state.js";
echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, AriaComponent, GraphicComponent, CanvasRenderer]);
const charts = /* @__PURE__ */ new Map();
function resize() {
  charts.forEach((c) => c.resize());
}
new ResizeObserver(resize).observe(document.documentElement);
const colors = ["#abce8b", "#80c5bb", "#d4ac75", "#a6a1d7", "#d88070"];
function plot(id, x, series, onClick, extra = {}) {
  let c = charts.get(id);
  if (!c) {
    c = echarts.init($(id));
    charts.set(id, c);
  }
  c.setOption({ animation: !matchMedia("(prefers-reduced-motion: reduce)").matches, animationDuration: 250, color: colors, aria: { enabled: true }, textStyle: { fontFamily: "sans-serif" }, tooltip: { trigger: "axis", confine: true, backgroundColor: "#26352f", borderColor: "#44534b", textStyle: { color: "#f1f2e9" } }, legend: { top: 0, textStyle: { color: "#aab6a8" }, icon: "circle", itemWidth: 8 }, grid: { left: 48, right: 18, top: 42, bottom: 40 }, xAxis: { type: "category", data: x, axisLabel: { color: "#aab6a8", formatter: (v) => /^\d{4}-/.test(v) ? v.slice(5) : v }, axisLine: { lineStyle: { color: "#354239" } }, axisTick: { show: false } }, yAxis: { type: "value", axisLabel: { color: "#aab6a8" }, splitLine: { lineStyle: { color: "#2a382f" } }, scale: !series.some((s) => s.type === "bar"), ...series.some((s) => s.type === "bar") ? { min: 0 } : {} }, graphic: series.some((s) => s.data.some((v) => v != null)) ? [] : [{ type: "text", left: "center", top: "middle", style: { text: "所选范围暂无记录", fill: "#a5b4a7", fontSize: 14 } }], series: series.map((s) => ({ showSymbol: false, connectNulls: false, barMaxWidth: 22, ...s })), ...extra }, true);
  c.off("click");
  if (onClick) c.on("click", (p) => onClick(x[p.dataIndex]));
  return c;
}
const line = (name, data, color) => ({ name, type: "line", data, ...color ? { itemStyle: { color } } : {} });
function bands(rows, metric, stat = "p50", outer = false) {
  const lo = outer ? "p10" : "p25", hi = outer ? "p90" : "p75";
  const values = rows.map((r) => metric ? r[metric] || {} : r);
  return [{ name: "", type: "line", stack: "band", data: values.map((v) => v[lo] ?? null), lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 }, itemStyle: { opacity: 0 }, silent: true, tooltip: { show: false } }, { name: outer ? "P10–P90" : "P25–P75", type: "line", stack: "band", data: values.map((v) => v[lo] != null && v[hi] != null ? v[hi] - v[lo] : null), lineStyle: { opacity: 0 }, areaStyle: { color: "#80c5bb", opacity: 0.18 }, itemStyle: { opacity: 0 }, tooltip: { show: false } }, line(stat === "mean" ? "均值" : "中位数", values.map((v) => v[stat] ?? null), "#80c5bb")];
}
function renderTrends(data, onDay) {
  const days = data.days || [], x = days.map((d) => d.date), vals = (k) => days.map((d) => d.summary?.[k] ?? null);
  const steps = vals("steps");
  plot("steps-chart", x, [{ name: "步数", type: "bar", data: steps, itemStyle: { color: "#abce8b", borderRadius: [3, 3, 0, 0] } }, ...data.grain && data.grain !== "day" ? [] : [line("7 日滚动均值", days.map((d) => d.steps_rolling_mean ?? null), "#ead2a3")]], onDay);
  const source = $("activity-source").value;
  const activityKeys = [...new Set(days.flatMap((d) => Object.keys(d[source] || {})))];
  $("activity-note").textContent = source === "activity" ? "已识别活动片段；与完整运动记录分别统计。" : "运动记录的有效活动分钟；不与日常片段相加。";
  const activityNames = { slow_walking: "慢走", fast_walking: "快走", running: "跑步", light_activity: "轻活动", outdoor_running: "户外跑步", walking: "步行", outdoor_cycling: "户外骑行", pool_swimming: "泳池游泳", football: "足球", rope_skipping: "跳绳", hiking: "徒步", strength_training: "力量训练" };
  plot("activity-chart", x, activityKeys.map((k) => ({ name: activityNames[k] || "未知类型（" + k.replace("unknown_", "") + "）", type: "bar", stack: "activity", data: days.map((d) => d[source]?.[k] ?? null) })), onDay);
  const overview = data.summary || {};
  const minutes = overview.workout_minutes, frequency = overview.workout_count, distance = overview.running_distance_meters;
  $("activity-summary").textContent = source === "workout_activity" ? `运动 ${number(frequency?.value)} 次 · 活动 ${number(minutes?.value, 1)} 分钟 · 有记录日均 ${number(minutes?.day_mean, 1)} 分钟` : `步行 ${number(overview.walking_minutes?.value, 1)} 分钟 · 跑步 ${number(overview.running_minutes?.value, 1)} 分钟 · 跑步距离 ${number(distance?.value == null ? null : distance.value / 1e3, 2)} km（来自日汇总，不与片段相加）`;
  $("steps-unit").textContent = data.grain === "week" ? "每周步数合计" : data.grain === "month" ? "每月步数合计" : "步数 · 7 日均线（按已观测日）";
  const stat = $("statistic").value, outer = $("band").value === "outer";
  plot("heart-chart", x, [...bands(days, "heart_rate", stat, outer), { ...line("静息心率", vals("resting_hr"), "#d4ac75") }], onDay);
  plot("stress-chart", x, bands(days, "stress", stat, outer), onDay);
  const sleepMetric = $("sleep-metric").value;
  const sleepSeries = sleepMetric === "score" ? [line("睡眠评分", vals("sleep_score"))] : sleepMetric === "timing" ? [line("入睡时间", vals("sleep_onset_minutes")), line("醒来时间", vals("sleep_wake_minutes"))] : [...["deep", "light", "rem", "awake"].map((s, i) => ({ name: ["深睡", "浅睡", "REM", "清醒"][i], type: "bar", stack: "sleep", data: vals("sleep_" + s + "_minutes") })), line("可识别睡眠", vals("actual_sleep_minutes"), "#efe3bd")];
  plot("sleep-chart", x, sleepSeries, onDay, sleepMetric === "timing" ? { yAxis: { type: "value", scale: true, axisLabel: { color: "#aab6a8", formatter: (v) => {
    const m = (v % 1440 + 1440) % 1440;
    return String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(Math.round(m % 60)).padStart(2, "0");
  } }, splitLine: { lineStyle: { color: "#2a382f" } } } } : {});
  const training = $("training-metric").value;
  plot("training-chart", x, (training === "load" ? ["atl", "ctl", "tsb"] : [training]).map((k) => line(k.toUpperCase(), vals(k))), onDay);
  renderMetrics(data);
}
export {
  bands,
  plot,
  renderTrends,
  resize
};
