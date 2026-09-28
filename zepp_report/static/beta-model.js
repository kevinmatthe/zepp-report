const valid=value=>typeof value==='number'&&Number.isFinite(value);
export function metricValue(day,key){
 const s=day.summary||{};
 const total=s.actual_sleep_minutes,deep=s.sleep_deep_minutes;
 const paired=valid(total)&&total>0&&valid(deep)&&deep>=0&&deep<=total;
 const values={sleep:valid(total)&&total>0?total:null,deepMinutes:paired?deep:null,deepShare:paired?deep/total*100:null,heart:day.heart_rate?.p50,resting:s.resting_hr,spo2:s.spo2_avg??day.spo2?.mean,steps:s.steps};
 return valid(values[key])?values[key]:null;
}
export function summarizePeriod(days,today='9999-12-31'){
 const complete=days.filter(day=>day.date<today),result={};
 for(const key of ['sleep','deepMinutes','deepShare','heart','resting','spo2','steps']){
  const available=complete.filter(day=>metricValue(day,key)!==null);
  let value=available.length?available.reduce((sum,day)=>sum+metricValue(day,key),0)/available.length:null;
  if(key==='deepShare'&&available.length)value=available.reduce((sum,day)=>sum+day.summary.sleep_deep_minutes,0)/available.reduce((sum,day)=>sum+day.summary.actual_sleep_minutes,0)*100;
  result[key]={value,valid:available.length,total:complete.length};
 }
 const observed=complete.filter(day=>metricValue(day,'steps')!==null);
 result.stepsTotal={value:observed.length?observed.reduce((sum,day)=>sum+metricValue(day,'steps'),0):null,valid:observed.length,total:complete.length};
 return result;
}
export function change(current,previous){
 const delta=valid(current)&&valid(previous)?current-previous:null;
 return {delta,percent:delta!==null&&previous>0?delta/previous*100:null};
}
export const shiftDate=(date,offset)=>new Date(Date.parse(date+'T12:00:00Z')+offset*86400000).toISOString().slice(0,10);
