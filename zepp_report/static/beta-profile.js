import {createBandControls,bandSeries} from './beta-bands.js';
import {shiftDate} from './beta-model.js';
export function createProfile({api,echarts,getToday,getTimezone}){
 const $=id=>document.getElementById('profile-'+id);
 let range=null,data=null,detail=null,instance=null,controller,generation=0,live=false;
 const clock=m=>`${String(Math.floor(m/60)).padStart(2,'0')}:${String(m%60).padStart(2,'0')}`;
 const number=v=>typeof v==='number'?v.toLocaleString('zh-CN',{maximumFractionDigits:1}):'—';
 const controls=createBandControls($('band-controls'),'profile','日内节律',render);
 function dates(){
  const day=$('day').value;
  $('day').min=range.from;$('day').max=range.to;$('prev').disabled=day===range.from;$('next').disabled=day===range.to;
  const length=Math.round((Date.parse(range.to)-Date.parse(range.from))/86400000)+1;
  const offset=Math.round((Date.parse(day)-Date.parse(range.from))/86400000);
  const start=Math.max(0,Math.min(offset-2,length-5));
  $('date-buttons').innerHTML=Array.from({length:Math.min(5,length)},(_,i)=>shiftDate(range.from,start+i)).map(d=>`<button type="button" data-day="${d}" aria-pressed="${d===day}">${d.slice(5)}</button>`).join('');
 }
 function status(){
  if(!detail)return;
  const today=$('day').value===getToday(),metric=$('metric').value;
  const observed=(detail[metric]||[]).filter(x=>Number.isFinite(x.value)&&Number.isFinite(x.time));
  const last=observed.length?Math.max(...observed.map(x=>x.time)):null;
  $('status').className=today&&live&&last?'profile-live':'';
  $('status').textContent=`${$('day').value}${today?' · 今日记录，随归档更新':''} · ${last?'最后观测 '+new Intl.DateTimeFormat('zh-CN',{timeZone:getTimezone(),hour:'2-digit',minute:'2-digit'}).format(new Date(last)):'暂无该指标观测'}`;
 }
 function render(){
  if(!data||!detail)return;
  const {lower,upper,show}=controls.read(),metric=$('metric').value,unit=metric==='heart_rate'?' bpm':metric==='spo2'?'%':'';
  const buckets=data.buckets||[],points=new Map((detail.profiles?.[metric]||[]).map(p=>[p.minute,p.value]));
  const series=[{name:'区间中位数',type:'line',data:buckets.map(b=>b.n>=2?b.p50:null),lineStyle:{width:2},itemStyle:{color:'#c0d79c'}},{name:'所选日',type:'line',data:buckets.map(b=>points.get(b.minute)??null),lineStyle:{width:2},itemStyle:{color:'#d4ac75'}}];
  if(show)series.push(...bandSeries(buckets.map(b=>b.n>=5?b:{}),lower,upper,'同一时刻'));
  $('legend').innerHTML=`<span class="legend-current">区间中位数</span><span class="legend-selected">所选日</span>${show?`<span class="legend-band">P${lower}–P${upper} · 跨日分布</span>`:''}`;
  if(!instance)instance=echarts.init($('chart'));
  instance.setOption({animation:false,aria:{enabled:true},grid:{left:45,right:20,top:16,bottom:32},xAxis:{type:'category',data:buckets.map(b=>clock(b.minute)),axisLabel:{color:'#a5b4a7',interval:47},axisLine:{lineStyle:{color:'#344338'}},axisTick:{show:false}},yAxis:{type:'value',scale:true,axisLabel:{color:'#a5b4a7'},splitLine:{lineStyle:{color:'#314333'}}},tooltip:{trigger:'axis',confine:true,backgroundColor:'#263c2d',borderColor:'#657b54',textStyle:{color:'#edf0e5'},formatter:items=>{const b=buckets[items[0]?.dataIndex];if(!b)return '';return `${clock(b.minute)} · ${b.n} 天<br>区间中位数 ${number(b.p50)}${unit}<br>所选日 ${number(points.get(b.minute))}${unit}${show?`<br>P${lower}–P${upper} ${number(b.n>=5?b['p'+lower]:null)}–${number(b.n>=5?b['p'+upper]:null)}${unit}`:''}`;}},graphic:series.slice(0,2).some(s=>s.data.some(v=>v!=null))?[]:[{type:'text',left:'center',top:'middle',style:{text:'暂无足够观测',fill:'#afbdab'}}],series:series.map(s=>({showSymbol:false,connectNulls:false,...s}))},true);
  status();instance.resize();
 }
 async function load(){
  if(!range)return;
  controller?.abort();controller=new AbortController();const id=++generation;
  dates();data=detail=null;instance?.clear();$('status').className='';$('status').textContent='正在读取日内记录…';$('legend').textContent='';
  const metric=$('metric').value,p=new URLSearchParams({from_date:range.from,to_date:range.to,metric,full_percentiles:'true'});
  try{
   const [baseline,day]=await Promise.all([api('/api/analytics/profile?'+p,'GET',undefined,controller.signal),api('/api/days/'+$('day').value,'GET',undefined,controller.signal)]);
   if(id!==generation)return;data=baseline;detail=day;render();
  }catch(error){if(error.name!=='AbortError'&&id===generation)$('status').textContent='日内记录读取失败，请重试。';}
 }
 function choose(day){if(!range||!day)return;$('day').value=day<range.from?range.from:day>range.to?range.to:day;load();}
 $('day').onchange=()=>choose($('day').value);$('prev').onclick=()=>choose(shiftDate($('day').value,-1));$('next').onclick=()=>choose(shiftDate($('day').value,1));$('metric').onchange=load;
 $('date-buttons').onclick=e=>{const b=e.target.closest('[data-day]');if(b)choose(b.dataset.day);};
 new ResizeObserver(()=>instance?.resize()).observe($('chart'));
 return {setRange:async(from,to)=>{const changed=!range||range.from!==from||range.to!==to;range={from,to};if(changed)$('day').value=to;await load();},setLive:value=>{live=value;status();},clear:()=>{generation++;controller?.abort();data=detail=range=null;instance?.clear();$('status').textContent='';}};
}
