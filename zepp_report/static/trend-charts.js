import {renderMetrics} from "./metric-cards.js";
import * as echarts from "echarts/core";
import { LineChart, BarChart, ScatterChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, AriaComponent, GraphicComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { $, number, escape } from "./state.js";
echarts.use([LineChart, BarChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, AriaComponent, GraphicComponent, CanvasRenderer]);
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
  c.setOption({ animation: !matchMedia("(prefers-reduced-motion: reduce)").matches, animationDuration: 250, color: colors, aria: { enabled: true }, textStyle: { fontFamily: "sans-serif" }, tooltip: { trigger: "axis", confine: true, backgroundColor: "#26352f", borderColor: "#44534b", textStyle: { color: "#f1f2e9" } }, legend: { top: 0, textStyle: { color: "#aab6a8" }, icon: "circle", itemWidth: 8 }, grid: { left: 48, right: 18, top: 42, bottom: 40 }, xAxis: { type: "category", data: x, axisLabel: { color: "#aab6a8", formatter: (v) => /^\d{4}-/.test(v) ? v.slice(5) : v }, axisLine: { lineStyle: { color: "#354239" } }, axisTick: { show: false } }, yAxis: { type: "value", axisLabel: { color: "#aab6a8" }, splitLine: { lineStyle: { color: "#2a382f" } }, scale: !series.some((s) => s.type === "bar"), ...series.some((s) => s.type === "bar") ? { min: 0 } : {} }, graphic: series.some((s) => s.data.some((v) => v != null && (typeof v !== 'object' || v.value != null))) ? [] : [{ type: "text", left: "center", top: "middle", style: { text: "所选范围暂无记录", fill: "#a5b4a7", fontSize: 14 } }], series: series.map((s) => ({ showSymbol: false, connectNulls: false, barMaxWidth: 22, ...s })), ...extra }, true);
  c.off("click");
  if (onClick) c.on("click", (p) => onClick(x[p.dataIndex]));
  return c;
}
const line = (name, data, color) => ({ name, type: "line", data, ...color ? { itemStyle: { color } } : {} });
const selectedBand=()=>[$('band-low').value,$('band-high').value];
function bands(rows, metric, stat = "p50", bounds = ['p25','p75']) {
  const [lo,hi]=bounds;
  const values = rows.map((r) => metric ? r[metric] || {} : r);
  return [{ name: "", type: "line", stack: "band", data: values.map((v) => v[lo] ?? null), lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 }, itemStyle: { opacity: 0 }, silent: true, tooltip: { show: false } }, { name: `${lo.toUpperCase()}–${hi.toUpperCase()}`, type: "line", stack: "band", data: values.map((v) => v[lo] != null && v[hi] != null ? v[hi] - v[lo] : null), lineStyle: { opacity: 0 }, areaStyle: { color: "#80c5bb", opacity: 0.18 }, itemStyle: { opacity: 0 }, tooltip: { show: false } }, line(stat === "mean" ? "均值" : "中位数", values.map((v) => v[stat] ?? null), "#80c5bb")];
}
function renderTrends(data, onDay) {
  const days = data.days || [], x = days.map((d) => d.date), vals = (k) => days.map((d) => d.summary?.[k] ?? null);
  const comparing=!!data.comparison && data.comparison_mode!=='none';
  const baselineLabel=data.comparison_mode==='year'?'去年同期':'上期';
  const baseline=new Map((data.comparison_days||[]).map(d=>[d.aligned_date,d]));
  const comparePlot=(id,series,specs,extra={})=>{
    const previous=comparing?specs.map(([name,getValue],index)=>({
      ...line(`${baselineLabel} · ${name}`,x.map(date=>{
        const row=baseline.get(date);
        return row?{value:getValue(row)??null,sourceDate:row.from_date?`${row.from_date} — ${row.to_date}`:row.date}:null;
      }),['#d4ac75','#b7b0e1','#e5a397'][index%3]),
      lineStyle:{type:'dashed',width:2},symbol:'circle',symbolSize:5,showSymbol:true,z:4,
    })):[];
    const current=series.map(s=>comparing?{
      ...s,name:s.name&&s.stack!=='band'?`本期 · ${s.name}`:s.name,
      data:s.data.map((value,i)=>value==null?null:{value,sourceDate:days[i].from_date?`${days[i].from_date} — ${days[i].to_date}`:days[i].date}),
    }:s);
    return plot(id,x,[...current,...previous],onDay,{
      ...extra,
      legend:{type:'scroll',top:0,textStyle:{color:'#c7cebf'},itemWidth:16},
      ...(comparing?{tooltip:{trigger:'axis',confine:true,backgroundColor:'#26352f',borderColor:'#44534b',textStyle:{color:'#f1f2e9'},formatter:items=>items.filter(p=>p.seriesName&&p.value!=null&&p.value!=='-'&&series[p.seriesIndex]?.tooltip?.show!==false).map(p=>`${escape(p.seriesName)} · ${escape(p.data?.sourceDate||p.axisValue)}<br><strong>${escape(number(p.value,1))}</strong>`).join('<br>')}}:{}),
    });
  };
  const steps = vals("steps");
  comparePlot("steps-chart", [{ name: "步数", type: comparing?"line":"bar", data: steps, itemStyle: { color: "#abce8b", borderRadius: [3, 3, 0, 0] } }, ...data.grain && data.grain !== "day" ? [] : [line("7 日滚动均值", days.map((d) => d.steps_rolling_mean ?? null), "#80c5bb")]], [['步数',d=>d.summary?.steps]]);
  const source = $("activity-source").value;
  const activityKeys = [...new Set(days.flatMap((d) => Object.keys(d[source] || {})))];
  $("activity-note").textContent = source === "activity" ? "已识别活动片段；与完整运动记录分别统计。" : "运动记录的有效活动分钟；不与日常片段相加。";
  const activityNames = { slow_walking: "慢走", fast_walking: "快走", running: "跑步", light_activity: "轻活动", outdoor_running: "户外跑步", walking: "步行", outdoor_cycling: "户外骑行", pool_swimming: "泳池游泳", football: "足球", rope_skipping: "跳绳", hiking: "徒步", strength_training: "力量训练" };
  comparePlot("activity-chart", activityKeys.map((k) => ({ name: activityNames[k] || "未知类型（" + k.replace("unknown_", "") + "）", type: "bar", stack: "activity", data: days.map((d) => d[source]?.[k] ?? null) })), [['总活动时长',d=>{
    const values=Object.values(d[source]||{}).filter(v=>v!=null);
    return values.length?values.reduce((sum,v)=>sum+v,0):null;
  }]]);
  const overview = data.summary || {};
  const minutes = overview.workout_minutes, frequency = overview.workout_count, distance = overview.running_distance_meters;
  $("activity-summary").textContent = source === "workout_activity" ? `运动 ${number(frequency?.value)} 次 · 活动 ${number(minutes?.value, 1)} 分钟 · 有记录日均 ${number(minutes?.day_mean, 1)} 分钟` : `步行 ${number(overview.walking_minutes?.value, 1)} 分钟 · 跑步 ${number(overview.running_minutes?.value, 1)} 分钟 · 跑步距离 ${number(distance?.value == null ? null : distance.value / 1e3, 2)} km（来自日汇总，不与片段相加）`;
  $("steps-unit").textContent = data.grain === "week" ? "每周步数合计" : data.grain === "month" ? "每月步数合计" : "步数 · 7 日均线（按已观测日）";
  const stat = $("statistic").value, bounds = selectedBand();
  comparePlot("heart-chart", [...bands(days, "heart_rate", stat, bounds), line("静息心率", vals("resting_hr"), "#a6a1d7")], [[stat==='mean'?'均值':'中位数',d=>d.heart_rate?.[stat]]]);
  comparePlot("stress-chart", bands(days, "stress", stat, bounds), [[stat==='mean'?'均值':'中位数',d=>d.stress?.[stat]]]);
  comparePlot('spo2-chart',bands(days,'spo2',stat,bounds),[[stat==='mean'?'均值':'中位数',d=>d.spo2?.[stat]]]);
  const oxygen=data.summary?.spo2_avg;
  $('spo2-value').textContent=number(oxygen?.value,1);
  $('spo2-note').textContent=`日均血氧按有记录日期平均 · 有效 ${oxygen?.valid_days??0} / ${oxygen?.total_days??days.length} 天。曲线为${stat==='mean'?'每日均值':'每日中位数'}，阴影为样本分布；缺失不补零。`;
  const sleepMetric = $("sleep-metric").value;
  const sleepSeries = sleepMetric === "score" ? [line("睡眠评分", vals("sleep_score"))] : sleepMetric === "timing" ? [line("入睡时间", vals("sleep_onset_minutes")), line("醒来时间", vals("sleep_wake_minutes"))] : [...["deep", "light", "rem", "awake"].map((s, i) => ({ name: ["深睡", "浅睡", "REM", "清醒"][i], type: "bar", stack: "sleep", data: vals("sleep_" + s + "_minutes") })), line("可识别睡眠", vals("actual_sleep_minutes"), "#efe3bd")];
  const sleepComparisons=sleepMetric==='score'?[['睡眠评分',d=>d.summary?.sleep_score]]:sleepMetric==='timing'?[['入睡时间',d=>d.summary?.sleep_onset_minutes],['醒来时间',d=>d.summary?.sleep_wake_minutes]]:[['可识别睡眠',d=>d.summary?.actual_sleep_minutes]];
  comparePlot("sleep-chart", sleepSeries, sleepComparisons, sleepMetric === "timing" ? { yAxis: { type: "value", scale: true, axisLabel: { color: "#aab6a8", formatter: (v) => {
    const m = (v % 1440 + 1440) % 1440;
    return String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(Math.round(m % 60)).padStart(2, "0");
  } }, splitLine: { lineStyle: { color: "#2a382f" } } } } : {});
  const training = $("training-metric").value;
  const trainingKeys=training === "load" ? ["atl", "ctl", "tsb"] : [training];
  comparePlot("training-chart", trainingKeys.map(k=>line(k.toUpperCase(),vals(k))),trainingKeys.map(k=>[k.toUpperCase(),d=>d.summary?.[k]]));
  renderMetrics(data);
}
export {
  bands,
  selectedBand,
  plot,
  renderTrends,
  resize
};
