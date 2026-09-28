import {$,number,escape} from './state.js';

const definitions = [
  {id:'steps-daily',label:'日均步数',key:'steps',unit:'步',mode:'daily',tag:'DAILY MOVEMENT',accent:true},
  {id:'steps-total',label:'有记录步数合计',key:'steps',unit:'步',mode:'total',tag:'EVERY STEP'},
  {id:'sleep-daily',label:'日均可识别睡眠',key:'actual_sleep_minutes',unit:'小时',divisor:60,digits:1,tag:'NIGHTLY RECOVERY'},
  {id:'heart-daily',label:'日典型心率',key:'heart_rate',unit:'bpm',tag:'YOUR RHYTHM',note:'每日心率中位数的平均值'},
  {id:'walking-daily',label:'日均步行时长',key:'walking_minutes',unit:'分钟',mode:'daily',tag:'TIME IN MOTION'},
  {id:'workout-count',label:'完整运动记录',key:'workout_count',unit:'次',mode:'total',tag:'SESSIONS RECORDED'},
  {id:'workout-minutes',label:'运动活动时长',key:'workout_minutes',unit:'分钟',mode:'total',tag:'ACTIVE MINUTES'},
  {id:'resting-heart',label:'日均静息心率',key:'resting_hr',unit:'bpm',tag:'REST & RESET'},
];
let lastFingerprint='',previousValues=new Map();
const finite = value => value != null && Number.isFinite(Number(value));

function fallback(data,key){
  // Only daily data may fill old-server responses; grouped rows do not recreate daily statistics.
  if(data.grain && data.grain!=='day')return {};
  const days=(data.days||[]).filter(d=>!data.summary_excludes_today||d.date!==data.today);
  const values=days.map(d=>key==='heart_rate'?d.heart_rate?.p50:d.summary?.[key]).filter(finite);
  const sum=values.reduce((a,b)=>a+Number(b),0),total=['steps','walking_minutes','workout_minutes','workout_count'].includes(key);
  return {value:values.length?(total?sum:sum/values.length):null,day_mean:values.length?sum/values.length:null,aggregation:total?'sum':'day_mean',valid_days:values.length,total_days:days.length};
}

export function renderMetrics(data){
  const cards=definitions.map(def=>{
    const m=data.summary?.[def.key]||fallback(data,def.key),divisor=def.divisor||1;
    const value=def.mode==='daily'?(m.day_mean??(m.aggregation==='sum'&&m.valid_days?m.value/m.valid_days:m.value)):m.value;
    const previous=def.mode==='daily'?(m.previous_day_mean??(m.previous_valid_days?m.previous/m.previous_valid_days:m.previous)):m.previous;
    const delta=finite(value)&&finite(previous)?(value-previous)/divisor:null;
    return {...def,m,value:finite(value)?value/divisor:null,previous:finite(previous)?previous/divisor:null,delta};
  });
  const fingerprint=JSON.stringify(cards);
  if(fingerprint===lastFingerprint)return;
  lastFingerprint=fingerprint;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  $('metrics').innerHTML=cards.map((c,index)=>{
    const valid=c.m.valid_days??0,total=c.m.total_days??0;
    const quality=c.m.comparison_quality==='insufficient'?' · 低覆盖参考':c.m.quality==='partial'?' · 部分日期有记录':'';
    const ratio=c.previous>0&&c.delta!=null&&['steps','walking_minutes','workout_minutes','workout_count'].includes(c.key)?c.delta/c.previous*100:null;
    const change=c.delta==null?'历史不足 / 未比较':`${c.delta>0?'+':''}${number(c.delta,c.digits??1)} ${c.unit}${ratio==null?'':` (${ratio>0?'+':''}${number(ratio,1)}%)`} · 基期 ${number(c.previous,c.digits??1)}`;
    const note=c.note||(c.mode==='total'?'已观测记录合计 · 缺日不补零':'仅有记录日期参与平均');
    return `<article class="metric ${c.accent?'metric-featured':''}" data-metric="${c.id}" style="--card-order:${index}"><div class="metric-topline"><p>${c.label}</p><span aria-hidden="true">${String(index+1).padStart(2,'0')}</span></div><div class="metric-value" aria-label="${c.label} ${number(c.value,c.digits??0)} ${c.unit}"><span class="metric-number">${number(c.value,c.digits??0)}</span><small>${c.unit}</small></div><p class="metric-delta">${escape(change)}</p><p class="metric-observations">有效 <strong>${valid}</strong> / ${total} 天${c.m.previous_total_days!=null?` · 基期 ${c.m.previous_valid_days||0} / ${c.m.previous_total_days} 天`:''}${quality}</p><div class="metric-bottom"><span class="metric-definition">${note}</span><span class="metric-code" aria-hidden="true">${c.tag}</span></div></article>`;
  }).join('');
  cards.forEach(c=>{
    const old=previousValues.get(c.id);
    if(!reduced && finite(c.value) && old!==undefined && old!==c.value){
      const el=$('metrics').querySelector(`[data-metric="${c.id}"] .metric-number`);
      el.animate([{opacity:.3,transform:'translateY(7px)',filter:'blur(2px)'},{opacity:1,transform:'translateY(0)',filter:'blur(0)'}],{duration:450,easing:'cubic-bezier(.2,.7,.2,1)'});
    }
    previousValues.set(c.id,c.value);
  });
  const steps=data.summary?.steps||fallback(data,'steps');
  $('hero-observation').innerHTML=`<span class="eyebrow">THE RECORD BEHIND THE NUMBERS</span><div class="observation-value">${number(steps.valid_days??0)}<span> / ${number(steps.total_days??0)} 天</span></div><span class="small muted">步数有记录的完整日期 · 缺失不计为零</span>`;
}
