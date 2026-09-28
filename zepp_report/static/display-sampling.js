// Presentation only: callers keep the full source arrays for tables and future zooms.
const valid=value=>value!==null&&value!==undefined&&Number.isFinite(Number(value));
export const pixelBudget=width=>Math.max(600,Math.min(1200,Math.floor(width*1.5)));
export function displaySamples(rows,metric,{from,to,budget=1000}={}){
  const source=rows.filter(p=>valid(p.time)).slice().sort((a,b)=>a.time-b.time);
  const limit=Math.max(8,Math.floor(budget));
  const low=from??source[0]?.time??0,high=to??source.at(-1)?.time??low;
  const visible=source.filter(p=>p.time>=low&&p.time<=high),observed=visible.filter(p=>valid(p.value));
  const result={points:observed,method:'raw',bucketMs:0,originalCount:observed.length,originalRows:visible.length,explicitMissing:visible.length-observed.length,missing:0,partialBuckets:0,emptyBuckets:0,from:low,to:high,budget:limit};
  if(observed.length<=limit)return result;
  if(metric==='steps'){
    // Verified step buffers contain one slot/minute. Align inferred missing slots
    // to that original clock, never to rounded display or browser-local times.
    const cadence=60000,origin=Number(source[0].time);
    const anchor=origin+Math.ceil((low-origin)/cadence)*cadence;
    const slots=Math.max(0,Math.floor((high-anchor)/cadence)+1);
    const minutes=Math.max(1,Math.ceil(slots/limit)),bucketMs=minutes*cadence;
    const buckets=Array.from({length:Math.ceil(slots/minutes)},(_,i)=>({time:anchor+i*bucketMs,value:null,count:0,expected:Math.min(minutes,slots-i*minutes),missing:0,partial:false,bucketStart:anchor+i*bucketMs,bucketEnd:anchor+Math.min((i+1)*minutes,slots)*cadence}));
    const times=buckets.map(()=>new Set());
    for(const point of observed){
      const index=Math.min(buckets.length-1,Math.max(0,Math.floor((point.time-anchor)/bucketMs)));
      const bucket=buckets[index];if(!bucket)continue;
      bucket.value=(bucket.value??0)+Number(point.value);bucket.count++;
      times[index].add(Number(point.time));
    }
    buckets.forEach((bucket,i)=>{bucket.missing=Math.max(0,bucket.expected-times[i].size);bucket.partial=bucket.missing>0});
    return {...result,method:'sum',points:buckets,bucketMs,missing:buckets.reduce((sum,p)=>sum+p.missing,0),partialBuckets:buckets.filter(p=>p.partial&&p.count>0).length,emptyBuckets:buckets.filter(p=>p.count===0).length};
  }
  // Every occupied time bin retains endpoints and extremes at their actual source
  // timestamps. Point marks remain unconnected, including across unobserved gaps.
  const binCount=Math.max(1,Math.floor(limit/4)),span=Math.max(1,high-low);
  const buckets=new Map();
  observed.forEach((point,index)=>{
    const bin=Math.min(binCount-1,Math.floor((point.time-low)/span*binCount));
    if(!buckets.has(bin))buckets.set(bin,[]);buckets.get(bin).push(index);
  });
  const indices=new Set();
  for(const group of buckets.values()){
    let minimum=group[0],maximum=group[0];
    for(const i of group){if(Number(observed[i].value)<Number(observed[minimum].value))minimum=i;if(Number(observed[i].value)>Number(observed[maximum].value))maximum=i}
    [group[0],group.at(-1),minimum,maximum].forEach(i=>indices.add(i));
  }
  return {...result,method:'envelope',bucketMs:span/binCount,points:[...indices].sort((a,b)=>a-b).map(i=>observed[i])};
}
