export function createBandControls(host,prefix,label,onChange){
 host.innerHTML=`<div class="band-heading"><strong>${label}分位范围</strong><output id="${prefix}-band-label">P25–P75</output><label class="band-toggle"><input id="${prefix}-band-show" type="checkbox" checked>显示条带</label></div><div class="band-editor"><label>下界 P<input id="${prefix}-band-low" type="number" min="0" max="95" step="5" value="25" aria-label="${label}分位下界"></label><div class="dual-range"><div class="dual-track"></div><input id="${prefix}-band-low-range" type="range" min="0" max="100" step="5" value="25" aria-label="${label}下界滑杆"><input id="${prefix}-band-high-range" type="range" min="0" max="100" step="5" value="75" aria-label="${label}上界滑杆"></div><label>上界 P<input id="${prefix}-band-high" type="number" min="5" max="100" step="5" value="75" aria-label="${label}分位上界"></label></div><div class="band-presets"><button type="button" data-preset-band="25,75">P25–P75</button><button type="button" data-preset-band="10,90">P10–P90</button><span>拖动每档 5%</span></div>`;
 const $=suffix=>host.querySelector(`#${prefix}-band-${suffix}`);
 let lower=25,upper=75;
 const sync=()=>{
  for(const suffix of ['low','low-range'])$(suffix).value=lower;
  for(const suffix of ['high','high-range'])$(suffix).value=upper;
  $('low').max=upper-5;$('high').min=lower+5;
  $('label').textContent=`P${lower}–P${upper}`;
  host.style.setProperty('--lower',lower+'%');host.style.setProperty('--upper',upper+'%');
  $('low-range').setAttribute('aria-valuetext','P'+lower);$('high-range').setAttribute('aria-valuetext','P'+upper);
 };
 for(const suffix of ['low','low-range','high','high-range']){
  const commit=()=>{const value=$(suffix).valueAsNumber;if(!Number.isFinite(value)){sync();return;}
   if(suffix.startsWith('low'))lower=Math.max(0,Math.min(upper-5,Math.round(value/5)*5));
   else upper=Math.min(100,Math.max(lower+5,Math.round(value/5)*5));
   sync();onChange();
  };
  if(suffix.endsWith('range'))$(suffix).oninput=commit;else $(suffix).onchange=commit;
  $(suffix).onblur=()=>{if(!$(suffix).value)sync();};
 }
 for(const button of host.querySelectorAll('[data-preset-band]'))button.onclick=()=>{[lower,upper]=button.dataset.presetBand.split(',').map(Number);sync();onChange();};
 $('show').onchange=onChange;sync();
 return {read:()=>({lower,upper,show:$('show').checked})};
}
export function bandSeries(rows,lower,upper,name='观测范围'){
 const pair=row=>{const a=row?.['p'+lower],b=row?.['p'+upper];return typeof a==='number'&&Number.isFinite(a)&&typeof b==='number'&&Number.isFinite(b)&&a<=b?[a,b]:null;};
 return [{name:'',type:'line',stack:'percentile',data:rows.map(r=>pair(r)?.[0]??null),lineStyle:{opacity:0},areaStyle:{opacity:0},itemStyle:{opacity:0},silent:true,tooltip:{show:false},showSymbol:false,connectNulls:false},{name:`${name} P${lower}–P${upper}`,type:'line',stack:'percentile',data:rows.map(r=>{const p=pair(r);return p?p[1]-p[0]:null;}),lineStyle:{opacity:0},areaStyle:{color:'#80c5bb',opacity:.16},itemStyle:{opacity:0},silent:true,tooltip:{show:false},showSymbol:false,connectNulls:false}];
}
