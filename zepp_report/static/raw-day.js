import {$,state,escape,number} from './state.js';
import {plot} from './trend-charts.js';

const metrics={steps:['分钟步数','步'],heart_rate:['心率','bpm'],stress:['压力',''],spo2:['血氧','%'],atl:['ATL','负荷'],ctl:['CTL','负荷'],tsb:['TSB','负荷'],trimp:['TRIMP','负荷'],sport_load:['运动负荷','负荷'],weekly_load:['周负荷','负荷'],sport_optimal_min:['运动负荷建议下限','负荷'],sport_optimal_max:['运动负荷建议上限','负荷'],vo2_max:['VO₂ Max','ml/kg/min']};
const names={slow_walking:'慢走',fast_walking:'快走',walking:'步行',running:'跑步',light_activity:'轻活动',outdoor_running:'户外跑步',outdoor_cycling:'户外骑行',pool_swimming:'泳池游泳',football:'足球',rope_skipping:'跳绳',hiking:'徒步',strength_training:'力量训练'};
const valid=value=>value!==null&&value!==undefined&&Number.isFinite(Number(value));
const exact=value=>valid(value)?escape(String(value)):'—';
let detail=null,chart=null,rawRows=[],offset=0,episodeOffset=0,workoutOffset=0,initialized=false;
const pageSize=50,episodePageSize=20;

function timestamp(value,short=false){
  if(!valid(value))return '—';
  return new Intl.DateTimeFormat('zh-CN',{timeZone:state.timezone,...(short?{}:{year:'numeric',month:'2-digit',day:'2-digit'}),hour:'2-digit',minute:'2-digit',second:'2-digit',fractionalSecondDigits:3,hourCycle:'h23'}).format(new Date(Number(value)));
}
function renderSamplePage(){
  const metric=$('raw-metric').value,[label,unit]=metrics[metric];
  const showCodes=metric==='steps'&&!!detail.activity_samples?.length;
  const codes=new Map((detail.activity_samples||[]).map(point=>[Number(point.time),point]));
  $('raw-category-heading').hidden=!showCodes;$('raw-intensity-heading').hidden=!showCodes;
  $('raw-value-heading').textContent=label+(unit?' · '+unit:'');
  $('raw-page').textContent=`${rawRows.length} 条原始记录 · 第 ${Math.floor(offset/pageSize)+1} / ${Math.max(1,Math.ceil(rawRows.length/pageSize))} 页 · ${state.timezone} · 表格保留完整列表，不随缩放删减`;
  $('raw-rows').innerHTML=rawRows.slice(offset,offset+pageSize).map(point=>`<tr><td><time data-timestamp="${point.time}" datetime="${new Date(Number(point.time)).toISOString()}">${escape(timestamp(point.time))}</time></td><td>${exact(point.value)}</td><td>${valid(point.value)?Number(point.value)===0?'已记录零值':'已记录':'缺失值'}</td>${showCodes?`<td>${exact(codes.get(Number(point.time))?.category_raw)}</td><td>${exact(codes.get(Number(point.time))?.intensity_raw)}</td>`:''}</tr>`).join('')||'<tr><td colspan="3">这一天没有该指标的原始采样记录。</td></tr>';
  $('raw-prev').disabled=offset===0;$('raw-next').disabled=offset+pageSize>=rawRows.length;
}
function updateZoom(start,end){
  $('raw-chart').dataset.zoomStart=String(start);$('raw-chart').dataset.zoomEnd=String(end);
  $('raw-zoom-start').value=String(start);$('raw-zoom-end').value=String(end);
}
function renderRawChart(){
  const metric=$('raw-metric').value,[label,unit]=metrics[metric];
  const source=detail?.event_series?.[metric]||detail?.[metric]||[];
  rawRows=source.filter(point=>valid(point.time)).slice().sort((a,b)=>a.time-b.time);
  const observed=rawRows.filter(point=>valid(point.value)),zeros=observed.filter(point=>Number(point.value)===0);
  const c=detail?.coverage?.[metric];
  $('raw-coverage').textContent=`已记录 ${number(observed.length)} 个有效采样点 · 其中零值 ${number(zeros.length)} 个 · 显式缺失 ${number(rawRows.length-observed.length)} 条${c?.expected_minutes!=null?` · 观测 ${number(c.observed_minutes)} / ${number(c.expected_minutes)} 分钟`:''}`;
  $('raw-date').textContent=`${detail.date} · ${state.timezone} · 原始采样时刻`;
  $('raw-note').textContent=(metric==='steps'?'柱图是设备记录的每分钟步数，底部圆点标记真实零值；缺失时刻不补柱。':'仅绘制实际记录的点，不连接未采样时段。')+' 不做 5 分钟聚合或数值插值。拖动图下滑块缩放，图内拖动平移。';
  if(metric==='steps'&&detail.steps_quality?.message)$('raw-note').textContent+=' '+detail.steps_quality.message;
  if(metric==='steps'&&detail.activity_samples?.length)$('raw-note').textContent+=' 表内活动与强度保留来源原始代码，含义及单位尚未确认。';
  const points=observed.map(point=>[Number(point.time),Number(point.value)]);
  const series=[{name:label,type:metric==='steps'?'bar':'scatter',data:points,symbolSize:5,barMaxWidth:12,itemStyle:{color:metric==='steps'?'#b9d697':'#80c5bb'},animation:false}];
  if(metric==='steps')series.push({name:'已记录零值',type:'scatter',data:zeros.map(p=>[Number(p.time),0]),symbolSize:5,itemStyle:{color:'#e1b676'},animation:false});
  chart=plot('raw-chart',[],series,null,{
    animation:false,
    grid:{left:48,right:20,top:40,bottom:85},
    xAxis:{type:'time',axisLabel:{color:'#aab6a8',formatter:value=>timestamp(value,true).slice(0,8)},axisLine:{lineStyle:{color:'#354239'}},splitLine:{show:false}},
    yAxis:{type:'value',name:unit,nameTextStyle:{color:'#aab6a8'},scale:metric!=='steps',...(metric==='steps'?{min:0}:{}),axisLabel:{color:'#aab6a8'},splitLine:{lineStyle:{color:'#2a382f'}}},
    tooltip:{trigger:'item',confine:true,formatter:point=>`${escape(timestamp(point.value[0]))}<br>${escape(label)}：${exact(point.value[1])} ${escape(unit)}`},
    dataZoom:[{type:'slider',start:0,end:100,bottom:8,height:25,filterMode:'none',showDataShadow:false,labelFormatter:value=>timestamp(value,true),textStyle:{color:'#aab6a8'},borderColor:'#43563f',fillerColor:'#b9d69725',handleStyle:{color:'#b9d697'}},{type:'inside',start:0,end:100,filterMode:'none',zoomOnMouseWheel:'ctrl',moveOnMouseMove:true,moveOnMouseWheel:false}],
    graphic:observed.length?[]:[{type:'text',left:'center',top:'middle',style:{text:'该日暂无原始采样记录',fill:'#a5b4a7',fontSize:14}}],
  });
  updateZoom(0,100);
  chart.off('datazoom');chart.on('datazoom',event=>{const zoom=event.batch?.[0]||event;const current=chart.getOption().dataZoom[0];updateZoom(zoom.start??current.start,zoom.end??current.end)});
  renderSamplePage();
}
function renderEpisodes(){
  const episodes=detail.activities||[],workouts=detail.workouts||[];
  const range=(count,offset,size)=>`${count} 条记录 · 第 ${Math.floor(offset/size)+1} / ${Math.max(1,Math.ceil(count/size))} 页 · ${state.timezone}`;
  $('activity-page').textContent=range(episodes.length,episodeOffset,episodePageSize)+' · 日常片段与完整运动记录不相加';
  $('activity-rows').innerHTML=episodes.slice(episodeOffset,episodeOffset+episodePageSize).map(a=>`<tr><td>${escape(timestamp(a.start))}</td><td>${escape(timestamp(a.end))}</td><td>${escape(names[a.type]||a.type||'未知')} / ${escape(a.mode??'—')}</td><td>${exact(a.minutes)}</td><td>${exact(a.steps)}</td><td>${exact(a.distance_meters)}</td><td>${exact(a.calories)}</td></tr>`).join('')||'<tr><td colspan="7">暂无日常活动片段。</td></tr>';
  $('workout-page').textContent=range(workouts.length,workoutOffset,episodePageSize)+' · — 表示来源没有提供该字段';
  $('workout-rows').innerHTML=workouts.slice(workoutOffset,workoutOffset+episodePageSize).map(w=>`<tr><td>${escape(w.id??'—')}</td><td>${escape(timestamp(w.start))}</td><td>${escape(timestamp(w.end))}</td><td>${escape(names[w.type]||w.type||'未知')} / ${escape(w.type_code??'—')}</td><td>${exact(w.minutes)}</td><td>${exact(w.distance_meters)}</td><td>${exact(w.calories)}</td><td>${exact(w.average_heart_rate)}</td></tr>`).join('')||'<tr><td colspan="8">暂无完整运动记录。</td></tr>';
  $('activity-prev').disabled=episodeOffset===0;$('activity-next').disabled=episodeOffset+episodePageSize>=episodes.length;
  $('workout-prev').disabled=workoutOffset===0;$('workout-next').disabled=workoutOffset+episodePageSize>=workouts.length;
}
function setup(){
  if(initialized)return;initialized=true;
  $('raw-metric').onchange=()=>{offset=0;renderRawChart()};
  $('raw-prev').onclick=()=>{offset=Math.max(0,offset-pageSize);renderSamplePage()};
  $('raw-next').onclick=()=>{offset+=pageSize;renderSamplePage()};
  const zoom=()=>{let start=Number($('raw-zoom-start').value),end=Number($('raw-zoom-end').value);if(start>=end)end=Math.min(100,start+1);chart?.dispatchAction({type:'dataZoom',start,end})};
  $('raw-zoom-start').oninput=zoom;
  $('raw-zoom-end').oninput=()=>{if(Number($('raw-zoom-end').value)<=Number($('raw-zoom-start').value))$('raw-zoom-start').value=String(Number($('raw-zoom-end').value)-1);zoom()};
  $('raw-reset').onclick=()=>{chart?.dispatchAction({type:'dataZoom',start:0,end:100})};
  for(const prefix of ['activity','workout'])for(const [suffix,direction] of [['prev',-1],['next',1]])$(prefix+'-'+suffix).onclick=()=>{if(prefix==='activity')episodeOffset=Math.max(0,episodeOffset+direction*episodePageSize);else workoutOffset=Math.max(0,workoutOffset+direction*episodePageSize);renderEpisodes()};
}
export function renderRawDay(next){
  setup();if(detail===next)return;
  detail=next;offset=0;episodeOffset=0;workoutOffset=0;
  const selected=$('raw-metric').value;
  const available=Object.keys(metrics).filter(key=>['steps','heart_rate','stress','spo2'].includes(key)||detail.event_series?.[key]?.length);
  $('raw-metric').innerHTML=available.map(key=>`<option value="${key}">${metrics[key][0]}${metrics[key][1]?' · '+metrics[key][1]:''}</option>`).join('');
  $('raw-metric').value=available.includes(selected)?selected:'steps';
  renderRawChart();renderEpisodes();
}
