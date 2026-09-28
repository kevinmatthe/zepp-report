import './beta.css';
import * as echarts from 'echarts/core';
import {LineChart} from 'echarts/charts';
import {GridComponent,TooltipComponent,LegendComponent,AriaComponent,GraphicComponent} from 'echarts/components';
import {CanvasRenderer} from 'echarts/renderers';
import {summarizePeriod,metricValue,change,shiftDate} from './beta-model.js';
echarts.use([LineChart,GridComponent,TooltipComponent,LegendComponent,AriaComponent,GraphicComponent,CanvasRenderer]);
const $=id=>document.getElementById(id);
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=(value,digits=1)=>value==null?'—':value.toLocaleString('zh-CN',{maximumFractionDigits:digits});
const definitions={sleep:{label:'日均可识别睡眠',unit:'分钟',duration:true},deepMinutes:{label:'日均深睡',unit:'分钟',duration:true},deepShare:{label:'深睡占比',unit:'%',points:true},heart:{label:'日典型心率',unit:'bpm'},resting:{label:'日均静息心率',unit:'bpm'},spo2:{label:'日均血氧',unit:'%',points:true},steps:{label:'日均步数',unit:'步',digits:0},stepsTotal:{label:'有记录步数合计',unit:'步',digits:0}};
const charts=new Map();
let timezone='Asia/Shanghai',today='',requestId=0,controller,current=null,previous=null,sleepMetric='deepMinutes',mode='previous';
const baselineLabel=()=>mode==='year'?'去年同期':'上期';
function valueText(value,key){
 if(value==null)return '—';
 const d=definitions[key];
 if(d.duration){const minutes=Math.round(value);return `${Math.floor(minutes/60)}小时${String(minutes%60).padStart(2,'0')}分`;}
 return `${number(value,d.digits??1)} ${d.unit}`;
}
function deltaText(value,key){
 if(value==null)return '—';
 return `${value>0?'+':''}${number(value,definitions[key].digits??1)} ${definitions[key].points?'个百分点':definitions[key].unit}`;
}
function unauthenticated(){
 controller?.abort();requestId++;current=previous=null;
 charts.forEach(c=>c.clear());$('results').hidden=true;$('main').hidden=true;$('login-view').hidden=false;
}
async function api(path,method='GET',body,signal){
 const r=await fetch(path,{method,signal,credentials:'same-origin',headers:method==='GET'?{}:{'Content-Type':'application/json','X-Zepp-Request':'1'},body:body===undefined?undefined:JSON.stringify(body)});
 if(r.status===401){unauthenticated();throw Error('请重新登录');}
 if(!r.ok){const d=await r.json().catch(()=>({}));throw Error(typeof d.detail==='string'?d.detail:`读取失败（${r.status}）`);}
 return r.json();
}
function chart(key,metric){
 const rows=current.days||[],base=new Map((previous?.days||[]).map((day,i)=>[i,day]));
 const active=!!previous;
 const labels=rows.map(d=>d.date);
 const data=rows.map(d=>metricValue(d,metric));
 const previousData=rows.map((day,i)=>{
  const prior=base.get(i);
  return prior&&day.date<today?{value:metricValue(prior,metric),sourceDate:prior.date}:null;
 });
 const series=[{name:'本期',type:'line',data,itemStyle:{color:'#c0d79c'},lineStyle:{width:2.5},symbolSize:5,showSymbol:rows.length<=31,connectNulls:false}];
 if(active)series.push({name:baselineLabel(),type:'line',data:previousData,itemStyle:{color:'#d5b17e'},lineStyle:{type:'dashed',width:2},symbolSize:4,showSymbol:rows.length<=31,connectNulls:false});
 let instance=charts.get(key);
 if(!instance){instance=echarts.init($(key+'-chart'));charts.set(key,instance);}
 instance.setOption({animation:!matchMedia('(prefers-reduced-motion: reduce)').matches,animationDuration:200,aria:{enabled:true},legend:{top:0,textStyle:{color:'#bcc8b5'},itemWidth:18},grid:{left:46,right:14,top:40,bottom:34},xAxis:{type:'category',data:labels,axisLabel:{color:'#aebca8',formatter:date=>date.slice(5)},axisLine:{lineStyle:{color:'#40553f'}},axisTick:{show:false}},yAxis:{type:'value',min:metric==='spo2'?bounds=>Number.isFinite(bounds.min)?Math.max(0,Math.floor(bounds.min-1)):0:metric==='heart'?undefined:0,max:metric==='spo2'?bounds=>Number.isFinite(bounds.max)?Math.min(100,Math.ceil(bounds.max+1)):100:metric==='deepShare'?bounds=>Number.isFinite(bounds.max)?Math.min(100,Math.max(10,Math.ceil(bounds.max/10)*10)):100:undefined,scale:metric==='heart',axisLabel:{color:'#aebca8'},splitLine:{lineStyle:{color:'#314333'}}},tooltip:{trigger:'axis',confine:true,backgroundColor:'#263c2d',borderColor:'#657b54',textStyle:{color:'#edf0e5'},formatter:items=>items.map(p=>`${escape(p.seriesName)} · ${escape(p.data?.sourceDate||p.axisValue)}<br><strong>${escape(valueText(p.value==='-'?null:p.value,metric))}</strong>`).join('<br>')},graphic:series.some(s=>s.data.some(v=>v!=null&&(typeof v!=='object'||v.value!=null)))?[]:[{type:'text',left:'center',top:'middle',style:{text:'这段时间暂无观测',fill:'#afbdab',fontSize:14}}],series},true);
}
function table(domain,keys,summary,old){
 const rows=keys.map(key=>{
  const a=summary[key],b=old?.[key],delta=change(a.value,b?.value).delta;
  const coverage=s=>s?`${s.valid}/${s.total} ${['sleep','deepMinutes','deepShare'].includes(key)?'夜':'天'}`:'—';
  const low=previous&&(a.valid/Math.max(a.total,1)<.7||(b?.valid??0)/Math.max(b?.total??0,1)<.7);
  const percent=key==='steps'?change(a.value,b?.value).percent:null;
  return `<tr data-stat="${key}"><td>${definitions[key].label}</td><td><strong>${valueText(a.value,key)}</strong><small>${coverage(a)}</small></td><td>${valueText(b?.value??null,key)}<small>${coverage(b)}</small></td><td class="difference">${deltaText(delta,key)}${percent==null?'':`<small>${percent>0?'+':''}${number(percent)}%</small>`}${low?'<span class="coverage-warning">低覆盖参考</span>':''}</td></tr>`;
 }).join('');
 $(domain+'-table').innerHTML=`<div class="table-wrap"><table><thead><tr><th scope="col">指标</th><th scope="col">本期</th><th scope="col">${previous?baselineLabel():'未比较'}</th><th scope="col">差异</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function render(){
 if(!current)return;
 const summary=summarizePeriod(current.days||[],today),old=previous?summarizePeriod(previous.days||[],today):null;
 $('metrics').innerHTML=['sleep','heart','spo2','steps'].map(key=>{
  const d=definitions[key],a=summary[key],delta=change(a.value,old?.[key]?.value).delta;
  const value=d.duration?valueText(a.value,key):`${number(a.value,d.digits??1)}<small>${d.unit}</small>`;
  return `<article class="metric" data-metric="${key}"><span class="metric-label">${d.label}</span><div class="metric-value">${value}</div><div class="metric-change">${previous?delta===null?'历史数据不足':`较${baselineLabel()} ${deltaText(delta,key)}`:'未开启对比'}</div><div class="metric-coverage">本期有效 ${a.valid}/${a.total} ${key==='sleep'?'夜':'天'}</div></article>`;
 }).join('');
 const from=current.from_date||$('from').value,to=current.to_date||$('to').value;
 $('periods').innerHTML=`<span>本期 ${escape(from)} — ${escape(to)}</span>${previous?`<span class="previous">${baselineLabel()} ${escape(previous.from_date)} — ${escape(previous.to_date)}</span>`:''}`;
 $('results').hidden=false;
 $('sleep-caption').textContent=sleepMetric==='deepShare'?'每日深睡占可识别睡眠的比例 · 周期差值用百分点表示':'每日深睡时长 · 同时对照总睡眠与深睡占比';
 for(const button of document.querySelectorAll('[data-sleep]'))button.setAttribute('aria-pressed',String(button.dataset.sleep===sleepMetric));
 chart('sleep',sleepMetric);chart('heart','heart');chart('spo2','spo2');chart('steps','steps');
 table('sleep',['sleep','deepMinutes','deepShare'],summary,old);table('heart',['heart','resting'],summary,old);table('spo2',['spo2'],summary,old);table('steps',['steps','stepsTotal'],summary,old);
 $('method-note').textContent=`时区：${timezone}。每行的覆盖天数／夜数按该指标单独计算，深睡占比按成对有效夜晚加权计算，不能用每日百分比的简单平均替代。`;
 charts.forEach(c=>c.resize());
}
async function load(){
 if(!$('range-form').reportValidity())return;
 const from=$('from').value,to=$('to').value;
 if(!from||!to||from>to||to>today||from<'1970-01-01'||(Date.parse(to)-Date.parse(from))/86400000>365){$('status').className='error';$('status').textContent='请选择不晚于今天、最多 366 天的有效日期范围。';return;}
 controller?.abort();controller=new AbortController();const id=++requestId;
 mode=$('compare').value;
 $('results').hidden=true;$('status').className='';$('status').textContent='正在读取两期档案…';$('results').setAttribute('aria-busy','true');
 const p=new URLSearchParams({from_date:from,to_date:to,compare:mode,grain:'day'});
 try{
  const next=await api('/api/analytics/trends?'+p,'GET',undefined,controller.signal);
  let base=null;
  if(next.comparison&&mode!=='none'){
   const q=new URLSearchParams({...next.comparison,compare:'none',grain:'day'});
   base=await api('/api/analytics/trends?'+q,'GET',undefined,controller.signal);
  }
  if(id!==requestId)return;
  current=next;previous=base;
  history.replaceState({},'',location.pathname+'?'+new URLSearchParams({from,to,compare:mode}));
  const oldLink='/?'+new URLSearchParams({from,to,compare:mode});
  document.querySelectorAll('.old-link,.compare-old').forEach(a=>a.href=oldLink);
  render();
  $('status').textContent=next.quality==='index_pending'?'部分日期的分析索引正在重建，数据可能尚不完整。':to===today?'今天的数据仍在更新；汇总与对比仅使用已结束日期。':'仅比较完整日期。空白不计为零，覆盖天数见各指标。';
 }catch(error){if(error.name!=='AbortError'&&id===requestId){$('status').className='error';$('status').textContent=error.message;}}
 finally{if(id===requestId)$('results').setAttribute('aria-busy','false');}
}
async function start(){
 try{
  const settings=await api('/api/settings');timezone=settings.timezone||'Asia/Shanghai';
  today=new Intl.DateTimeFormat('sv-SE',{timeZone:timezone}).format(new Date());
  const p=new URLSearchParams(location.search);$('from').value=p.get('from')||shiftDate(today,-30);$('to').value=p.get('to')||shiftDate(today,-1);
  $('from').max=$('to').max=today;$('from').min=$('to').min='1970-01-01';
  $('compare').value=['previous','year','none'].includes(p.get('compare'))?p.get('compare'):'previous';
  $('timezone').textContent=timezone;$('login-view').hidden=true;$('main').hidden=false;await load();
 }catch(error){if(!$('login-view').hidden)$('login-error').textContent='';else{$('main').hidden=false;$('status').textContent=error.message;}}
}
$('login-form').onsubmit=async event=>{event.preventDefault();const button=event.currentTarget.querySelector('button');button.disabled=true;try{await api('/api/login','POST',{password:$('password').value});$('password').value='';await start();}catch(error){$('login-error').textContent=error.message;}finally{button.disabled=false;}};
$('range-form').onsubmit=event=>{event.preventDefault();load();};$('compare').onchange=load;
for(const button of document.querySelectorAll('[data-days]'))button.onclick=()=>{$('from').value=shiftDate(today,-Number(button.dataset.days));$('to').value=shiftDate(today,-1);load();};
for(const button of document.querySelectorAll('[data-sleep]'))button.onclick=()=>{sleepMetric=button.dataset.sleep;render();};
$('logout').onclick=async()=>{try{await api('/api/logout','POST',{});unauthenticated();}catch(error){$('status').textContent=error.message;}};
new ResizeObserver(()=>charts.forEach(c=>c.resize())).observe(document.documentElement);
start();
