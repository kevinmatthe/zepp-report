import {$,state,escape,number} from './state.js';
const stages=[['awake','清醒'],['rem','REM'],['light','浅睡'],['deep','深睡']];
const names=Object.fromEntries(stages);
const valid=value=>value!=null&&Number.isFinite(Number(value));
function time(value,seconds=false){
  const parts=new Intl.DateTimeFormat('en-GB',{timeZone:state.timezone,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',...(seconds?{second:'2-digit'}:{}),hourCycle:'h23'}).formatToParts(new Date(value));
  const get=type=>parts.find(p=>p.type===type)?.value;
  return `${get('month')}/${get('day')} ${get('hour')}:${get('minute')}${seconds?':'+get('second'):''}`;
}
export function renderSleepNight(detail){
  const source=(detail.sleep_stages||[]).filter(s=>valid(s.start)&&valid(s.end)&&s.end>s.start).slice().sort((a,b)=>a.start-b.start);
  const summary=detail.summary||{},actual=summary.actual_sleep_minutes;
  const duration=valid(actual)?`${Math.floor(actual/60)}<small>小时</small>${number(actual%60)}<small>分钟</small>`:'—';
  if(!source.length){$('sleep-night').innerHTML=`<div class="section-heading"><h3>这一晚的睡眠</h3><span class="small muted">${escape(detail.date)}</span></div><p class="muted">暂无可展示的睡眠阶段区间。</p><p class="chart-note">可识别睡眠 ${number(actual)} 分钟；不依据起止跨度推测缺失阶段。</p>`;return}
  const start=Math.min(...source.map(s=>s.start)),end=Math.max(...source.map(s=>s.end)),span=end-start;
  const rows=[],known=source.filter(s=>Object.hasOwn(names,s.stage));let cursor=start;
  for(const row of source){if(row.start>cursor)rows.push({start:cursor,end:row.start,stage:'gap'});rows.push(row);cursor=Math.max(cursor,row.end)}
  const stageName=s=>names[s]||(s==='gap'?'未记录区间':'未识别阶段');
  $('sleep-night').innerHTML=`<div class="section-heading"><div><p class="eyebrow">YOUR NIGHT, IN DETAIL</p><h3>这一晚，怎样度过。</h3></div><span class="small muted">${escape(detail.date)} 醒来日</span></div><div class="sleep-summary"><div class="sleep-main-stat"><span>实际可识别睡眠</span><strong>${duration}</strong><small>仅计浅睡、深睡、REM</small></div><div><span>记录起点</span><strong>${time(start)}</strong><small>${state.timezone}</small></div><div><span>记录终点</span><strong>${time(end)}</strong><small>起止跨度 ${number(span/60000)} 分钟</small></div></div><div class="sleep-duration-grid">${stages.map(([key,label])=>`<div><i class="${key}"></i><span>${label}</span><strong>${number(summary['sleep_'+key+'_minutes'])}<small> 分钟</small></strong></div>`).join('')}</div><div class="sleep-lanes" aria-label="睡眠阶段区间：四行分别表示清醒、REM、浅睡、深睡，空白不是睡眠阶段">${stages.map(([key,label])=>`<div class="sleep-lane"><span class="sleep-lane-label">${label}</span><div class="sleep-lane-track">${known.map((s,i)=>s.stage!==key?'':`<button type="button" class="sleep-interval ${key}" data-sleep-index="${i}" data-start="${s.start}" data-end="${s.end}" style="left:${(s.start-start)/span*100}%;width:${(s.end-s.start)/span*100}%" aria-label="${label} ${time(s.start,true)} 至 ${time(s.end,true)}，${number((s.end-s.start)/60000,1)} 分钟" title="${label} ${time(s.start,true)} — ${time(s.end,true)}"></button>`).join('')}</div></div>`).join('')}<div class="sleep-axis"><span></span><div>${[0,.25,.5,.75,1].map((fraction,i)=>`<span class="sleep-tick tick-${i}" style="left:${fraction*100}%">${time(start+span*fraction).replace(' ','<br>')}</span>`).join('')}</div></div></div><p id="sleep-inspect" class="sleep-inspect" role="status">点击或用 Tab 选择一个区间，查看准确时间与时长。</p><p class="chart-note">空白表示没有已识别阶段，不连接跨越缺失区间。阶段覆盖 ${number(summary.sleep_stage_coverage==null?null:summary.sleep_stage_coverage*100,1)}% · 未识别 ${number(summary.sleep_gap_minutes,1)} 分钟 · 重叠 ${number(summary.sleep_overlap_minutes,1)} 分钟。</p><details id="sleep-table"><summary>查看全部睡眠区间（含未识别与空白）</summary><div class="table-scroll"><table><thead><tr><th>开始（${state.timezone}）</th><th>结束</th><th>阶段</th><th>分钟</th></tr></thead><tbody id="sleep-interval-rows">${rows.map(s=>`<tr><td>${time(s.start,true)}</td><td>${time(s.end,true)}</td><td>${stageName(s.stage)}</td><td>${number((s.end-s.start)/60000,2)}</td></tr>`).join('')}</tbody></table></div></details>`;
  $('sleep-night').querySelectorAll('[data-sleep-index]').forEach(button=>{
    const inspect=()=>{const s=known[Number(button.dataset.sleepIndex)];$('sleep-inspect').textContent=`${stageName(s.stage)} · ${time(s.start,true)} — ${time(s.end,true)} · ${number((s.end-s.start)/60000,1)} 分钟`;};
    button.onclick=inspect;button.onfocus=inspect;button.onmouseenter=inspect;
  });
}
