const assert=require('node:assert/strict');
const {buildSync}=require('esbuild');
const {mkdtempSync,rmSync}=require('node:fs');
const {tmpdir}=require('node:os');
const {join}=require('node:path');
(async()=>{
 const dir=mkdtempSync(join(tmpdir(),'zepp-beta-'));
 try{
  const outfile=join(dir,'model.mjs');
  buildSync({entryPoints:['zepp_report/static/beta-model.js'],bundle:true,format:'esm',platform:'node',outfile});
  const {summarizePeriod,metricValue,change}=await import(outfile);
  const days=[
   {date:'2026-09-01',summary:{actual_sleep_minutes:400,sleep_deep_minutes:100,steps:0},heart_rate:{p50:60}},
   {date:'2026-09-02',summary:{actual_sleep_minutes:200,sleep_deep_minutes:100,steps:200},heart_rate:{p50:80}},
   {date:'2026-09-03',summary:{actual_sleep_minutes:600}},
   {date:'2026-09-04',summary:{actual_sleep_minutes:200,sleep_deep_minutes:0}},
   {date:'2026-09-05',summary:{}},
   {date:'2026-09-06',summary:{steps:99999,actual_sleep_minutes:100,sleep_deep_minutes:90}},
  ];
  const result=summarizePeriod(days,'2026-09-06');
  assert.equal(result.steps.value,100,'recorded zero included; absent and unfinished day excluded');
  assert.equal(result.steps.valid,2);assert.equal(result.steps.total,5);
  assert.equal(result.deepShare.value,25,'weighted matched-night ratio, not mean of nightly percentages or unmatched denominator');
  assert.equal(result.deepShare.valid,3);
  assert.equal(result.deepMinutes.value,200/3);
  assert.equal(result.heart.value,70);
  assert.equal(result.spo2.value,null);
  assert.equal(metricValue(days[4],'steps'),null);
  assert.equal(metricValue(days[0],'steps'),0);
  assert.equal(metricValue({summary:{actual_sleep_minutes:0,sleep_deep_minutes:0}},'deepShare'),null);
  assert.equal(metricValue({summary:{actual_sleep_minutes:10,sleep_deep_minutes:20}},'deepShare'),null);
  assert.deepEqual(change(20,17),{delta:3,percent:3/17*100});
  assert.deepEqual(change(20,0),{delta:20,percent:null});
  assert.deepEqual(change(null,17),{delta:null,percent:null});
  assert.equal(summarizePeriod([]).deepShare.value,null);
  console.log('Beta statistics: paired sleep ratios, coverage, zeros, missing data and incomplete days passed');
 }finally{rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
