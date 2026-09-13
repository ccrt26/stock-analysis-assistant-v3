/* SVG charts: exact stored daily points; interpolation is visual only. */
(function(root){'use strict';
const M=root.PrismMath,V=M.valid;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,n=2)=>V(v)?v.toLocaleString('en-US',{minimumFractionDigits:n,maximumFractionDigits:n}):'—';
const pct=v=>V(v)?`${v>0?'+':''}${v.toFixed(2)}%`:'—';
const short=d=>d?d.slice(5).replace('-','/'):'—';
const mono='font-family:var(--mono);font-variant-numeric:tabular-nums';
let serial=0;
function chart(host,opts){
 const {rows,mode='line',relative=[],reference=null,target=null,recDate=null,metric='volumeShares',isIndex=false,animate=false}=opts;
 const cs=getComputedStyle(host),availableW=host.clientWidth-parseFloat(cs.paddingLeft||0)-parseFloat(cs.paddingRight||0);
 const W=Math.max(isIndex?820:650,availableW||650),H=isIndex?Math.min(620,Math.max(320,innerHeight*.60)):386;
 const L=26,R=74,T=43,P=H-147,VB=H-46,VT=P+40,pw=W-L-R,n=rows.length,x=i=>L+(i+.5)*pw/n;
 const count=rows.filter(r=>V(r.close)).length;
 const values=mode==='relative'?relative.flatMap(s=>s.values).filter(V):rows.flatMap(r=>mode==='candle'?[r.high,r.low]:[r.close]).filter(V);
 if(mode!=='relative'&&V(reference))values.push(reference);if(mode!=='relative'&&V(target))values.push(target);
 let lo=values.length?Math.min(...values):0,hi=values.length?Math.max(...values):1;
 const pad=Math.max((hi-lo)*.12,Math.abs(hi)*.002,.001);lo-=pad;hi+=pad;
 const y=v=>T+(hi-v)/(hi-lo)*(P-T);
 const field=metric==='amountYuan'?'amountYuan':'volumeShares',factor=field==='amountYuan'?1e8:1e6,unit=field==='amountYuan'?'亿元':'万手';
 const metricLabel=field==='amountYuan'?'成交额':'成交量';
 const volumes=rows.map(r=>V(r[field])&&r[field]>=0?r[field]:null),maxV=Math.max(1,...volumes.filter(V));
 const vy=v=>VB-(v/maxV)*(VB-VT);
 const uid=`chart-${++serial}`;
 host.dataset.slots=String(n);host.dataset.mode=mode;host.dataset.known=String(count);
 const text=(xx,yy,str,extra='')=>`<text x="${xx}" y="${yy}" fill="var(--muted)" font-size="10" style="${mono}" ${extra}>${esc(str)}</text>`;
 let bg=`<defs><pattern id="${uid}-dots" width="18" height="18" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".8" fill="currentColor" opacity=".13"/></pattern><clipPath id="${uid}-clip"><rect x="${L}" y="${T-25}" width="${pw}" height="${P-T+32}"/></clipPath></defs><rect x="${L}" y="${T}" width="${pw}" height="${P-T}" fill="url(#${uid}-dots)"/>`;
 for(let k=0;k<=4;k++){const v=hi-(hi-lo)*k/4,yy=y(v);bg+=`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="var(--line)" stroke-dasharray="2 6"/>`+text(W-R+12,yy+4,num(v,mode==='relative'?1:2))}
 const tick=M.tickIndices(n,5);
 tick.forEach(i=>{if(rows[i].date)bg+=text(x(i),H-20,short(rows[i].date),'text-anchor="middle" class="date-tick"')});
 bg+=`<line x1="${L}" y1="${P+22}" x2="${W-R}" y2="${P+22}" stroke="var(--line)"/>`+text(L,P+35,`${metricLabel} / ${unit}`)+text(W-R+12,VT+4,num(maxV/factor,1));
 const obs=rows.findIndex(r=>r.date===recDate);
 if(obs>=0){bg+=`<rect x="${x(obs)-pw/n/2}" y="${T}" width="${W-R-x(obs)+pw/n/2}" height="${P-T}" fill="var(--text)" opacity=".022"/><line x1="${x(obs)}" y1="${T-4}" x2="${x(obs)}" y2="${P}" stroke="var(--blue)" stroke-dasharray="3 6" opacity=".7"/><circle cx="${x(obs)}" cy="${P}" r="2" fill="var(--blue)"/>`+text(Math.min(W-R-108,x(obs)+7),T-15,`${short(recDate)} 开始观察`)}
 if(mode!=='relative'){
  if(V(reference))bg+=`<line x1="${L}" y1="${y(reference)}" x2="${W-R}" y2="${y(reference)}" stroke="var(--blue)" stroke-dasharray="4 5" opacity=".64"/>`+text(L+8,y(reference)-7,`参考价 ${num(reference)}`);
  if(V(target))bg+=`<line x1="${Math.max(L,obs>=0?x(obs):L)}" y1="${y(target)}" x2="${W-R}" y2="${y(target)}" stroke="var(--amber)" stroke-dasharray="4 6" opacity=".68"/>`+text(W-R-8,y(target)-9,`原观察目标 ${num(target)}`,'text-anchor="end"');
 }
 let paths='';
 const path=(values,color,width=1.6,dash='')=>`<path class="price-trace" d="${M.smoothPath(values,x,y)}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" ${dash?`stroke-dasharray="${dash}"`:''}/>`;
 if(mode==='relative'){
  relative.forEach((s,j)=>{paths+=path(s.values,s.color,j===0?2.4:1.4,j===2?'5 6':'');s.values.forEach((v,i)=>{if(V(v)&&(i===0||!V(s.values[i-1]))&&(i===n-1||!V(s.values[i+1])))paths+=`<circle cx="${x(i)}" cy="${y(v)}" r="2.5" fill="${s.color}"/>`})});
  bg+=text(L,T-16,'首个观察日收盘 = 100 · 各序列使用同一天，不改变原参考价');
 }else if(mode==='candle'){
  const cw=Math.min(15,pw/n*.56);
  rows.forEach((r,i)=>{if(![r.open,r.high,r.low,r.close].every(V))return;const col=r.close>=r.open?'var(--up)':'var(--down)';paths+=`<g class="candle" data-date="${r.date}"><line x1="${x(i)}" y1="${y(r.high)}" x2="${x(i)}" y2="${y(r.low)}" stroke="${col}" stroke-width="1.2"/><rect x="${x(i)-cw/2}" y="${Math.min(y(r.open),y(r.close))}" width="${cw}" height="${Math.max(1.2,Math.abs(y(r.open)-y(r.close)))}" fill="${col}" rx=".5"/></g>`});
  const closes=rows.map(r=>r.close);
  [5,10,20].forEach((n,j)=>{const full=opts.fullHistory||rows,ma=M.averageSeries(full.map(r=>r.close),n),byDate=new Map(full.map((r,i)=>[r.date,ma[i]]));paths+=path(rows.map(r=>byDate.get(r.date)??null),['var(--accent)','var(--blue)','var(--amber)'][j],.9)});
  // Call out exact visible extremes, with labels kept inside the plot.
  const good=rows.flatMap((r,i)=>V(r.high)&&V(r.low)?[{r,i}]:[]);
  if(good.length){const high=good.reduce((a,b)=>a.r.high>b.r.high?a:b),low=good.reduce((a,b)=>a.r.low<b.r.low?a:b);paths+=text(Math.max(L+32,Math.min(W-R-32,x(high.i))),y(high.r.high)-10,num(high.r.high),'text-anchor="middle"')+text(Math.max(L+32,Math.min(W-R-32,x(low.i))),Math.min(P+12,y(low.r.low)+15),num(low.r.low),'text-anchor="middle"')}
 }else{
  const closes=rows.map(r=>r.close);paths+=path(closes,'var(--accent)',2);
  if(obs>0){const observed=closes.map((v,i)=>i>=obs?v:null);paths+=path(observed,'var(--text)',2.3)}
  closes.forEach((v,i)=>{if(V(v)&&(i===0||!V(closes[i-1]))&&(i===n-1||!V(closes[i+1])))paths+=`<circle cx="${x(i)}" cy="${y(v)}" r="2.5" fill="var(--text)"/>`});
 }
 let marks='';
 const latest=rows.at(-1);const lastValue=mode==='relative'?relative[0]?.values.at(-1):latest.close;
 if(V(lastValue)){marks+=`<circle cx="${x(n-1)}" cy="${y(lastValue)}" r="2.5" fill="var(--text)"/><line x1="${x(n-1)}" y1="${y(lastValue)}" x2="${W-R+3}" y2="${y(lastValue)}" stroke="var(--muted)" stroke-dasharray="3 4"/><rect x="${W-R+3}" y="${y(lastValue)-10}" width="65" height="20" fill="var(--accent)" rx="3"/><text x="${W-R+35}" y="${y(lastValue)+4}" text-anchor="middle" fill="var(--bg)" font-size="10" style="${mono}">${num(lastValue,mode==='relative'?1:2)}</text>`}
 rows.forEach((r,i)=>{if(!V(volumes[i]))return;marks+=`<rect class="volume-bar" data-date="${r.date}" x="${x(i)-Math.min(13,pw/n*.54)/2}" y="${vy(volumes[i])}" width="${Math.min(13,pw/n*.54)}" height="${Math.max(.5,VB-vy(volumes[i]))}" rx=".6" fill="${r.close>=r.open?'var(--up)':'var(--down)'}" opacity=".53"/>`});
 if(volumes.filter(V).length){const av=M.averageSeries(volumes,5);marks+=`<path d="${M.smoothPath(av,x,vy)}" fill="none" stroke="var(--secondary)" opacity=".52" stroke-width=".8"/>`}else marks+=text(L+118,P+35,`${metricLabel}暂缺，不用另一指标冒充`);
 if(!values.length||!count)marks+=text((L+W-R)/2,(T+P)/2,'当前窗口暂无可绘制行情','text-anchor="middle"');
 if(isIndex&&!rows.some(r=>[r.open,r.high,r.low,r.close].every(V)))marks+=text((L+W-R)/2,(T+P)/2+23,'需原始开高低收；不能从收盘序列生成 K 线','text-anchor="middle"');
 host.innerHTML=`<div class="ohlc-readout" aria-live="off"></div><div class="svg-scroll"><svg class="price-chart" data-mode="${mode}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" tabindex="0" aria-label="${esc(opts.name)}，${n}个交易日${mode==='candle'?'K线':mode==='relative'?'相对走势':'收盘走势'}。方向键查看每日数值"><g>${bg}</g><g clip-path="url(#${uid}-clip)"><g class="trace-layer">${paths}</g></g><g>${marks}</g><g class="crosshair" style="display:none;pointer-events:none"><line class="cross-v" y1="${T}" y2="${VB}" stroke="var(--secondary)" stroke-dasharray="4 4"/><line class="cross-h" x1="${L}" x2="${W-R}" stroke="var(--secondary)" stroke-dasharray="4 4" opacity=".45"/><circle r="3" fill="var(--text)" stroke="var(--bg)"/></g><rect class="hit-area" x="${L}" y="${T}" width="${pw}" height="${VB-T}" fill="transparent"/></svg></div>`;
 const svg=host.querySelector('svg'),cross=host.querySelector('.crosshair'),tip=document.getElementById('chartTooltip');
 const readout=host.querySelector('.ohlc-readout');
 let selected=n-1;
 function inspect(i,e){selected=Math.max(0,Math.min(n-1,i));const r=rows[selected];
  const delta=V(r.close)&&V(rows[selected-1]?.close)&&rows[selected-1].close>0?(r.close/rows[selected-1].close-1)*100:null;
  readout.innerHTML=`<b>${r.date?short(r.date):'未提供日期'}</b><span>开 <em>${num(r.open)}</em></span><span>高 <em>${num(r.high)}</em></span><span>低 <em>${num(r.low)}</em></span><span>收 <em>${num(r.close)}</em></span><span class="${delta>0?'up':delta<0?'down':''}">${pct(delta)}</span><span>${metricLabel} <em>${num(V(r[field])?r[field]/factor:null)} ${unit}</em></span>`;
  if(!e)return;
  const value=mode==='relative'?relative[0]?.values[selected]:r.close;
  cross.style.display='';cross.querySelector('.cross-v').setAttribute('x1',x(selected));cross.querySelector('.cross-v').setAttribute('x2',x(selected));
  const yy=V(value)?y(value):P;cross.querySelector('.cross-h').setAttribute('y1',yy);cross.querySelector('.cross-h').setAttribute('y2',yy);cross.querySelector('circle').setAttribute('cx',x(selected));cross.querySelector('circle').setAttribute('cy',yy);cross.querySelector('circle').style.display=V(value)?'':'none';
  if(tip){tip.innerHTML=`<strong>${esc(opts.name)} <span>${r.date||'日期暂缺'}</span></strong><dl><div><dt>开盘 / 收盘</dt><dd>${num(r.open)} / ${num(r.close)}</dd></div><div><dt>最高 / 最低</dt><dd>${num(r.high)} / ${num(r.low)}</dd></div><div><dt>${metricLabel}</dt><dd>${num(V(r[field])?r[field]/factor:null)} ${unit}</dd></div>${mode==='relative'?relative.map(s=>`<div><dt>${esc(s.name)}</dt><dd>${num(s.values[selected])}</dd></div>`).join(''):''}</dl>`;tip.hidden=false;const rect=svg.getBoundingClientRect();const tx=e.clientX??rect.left+x(selected),ty=e.clientY??rect.top+yy;tip.style.left=Math.max(10,Math.min(innerWidth-tip.offsetWidth-12,tx+18))+'px';tip.style.top=Math.max(10,Math.min(innerHeight-tip.offsetHeight-12,ty+16))+'px'}
 }
 inspect(n-1);
 svg.addEventListener('pointermove',e=>{const rect=svg.getBoundingClientRect();const xx=(e.clientX-rect.left)*W/rect.width;inspect(Math.floor((xx-L)/pw*n),e)});
 svg.addEventListener('pointerleave',()=>{cross.style.display='none';if(tip)tip.hidden=true;inspect(n-1)});
 svg.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();inspect(selected+(e.key==='ArrowRight'?1:-1),{})}if(e.key==='Escape'){cross.style.display='none';if(tip)tip.hidden=true}});
 if(animate&&opts.motion){const layer=host.querySelector('.trace-layer');layer.animate([{clipPath:'inset(0 100% 0 0)'},{clipPath:'inset(0 0% 0 0)'}],{duration:920,easing:'cubic-bezier(.22,.68,.3,1)',fill:'none'});}
 return {svg,count,rows};
}
function spark(rows,{markDate=null}={}){
 const values=rows.map(r=>r.close),vs=values.filter(V);if(!vs.length)return '<div class="spark-empty">近20个交易日价格暂缺</div>';
 let lo=Math.min(...vs),hi=Math.max(...vs),pad=Math.max((hi-lo)*.14,hi*.002);lo-=pad;hi+=pad;
 const x=i=>4+i/Math.max(1,rows.length-1)*232,y=v=>57-(v-lo)/(hi-lo)*47,marker=rows.findIndex(r=>r.date===markDate);
 let h=`<path d="M4 60H236" stroke="var(--line)"/>`;
 if(marker>=0)h+=`<line x1="${x(marker)}" y1="9" x2="${x(marker)}" y2="61" stroke="var(--muted)" stroke-width=".7" stroke-dasharray="2 4"/><text x="${marker>14?x(marker)-3:x(marker)+3}" y="8" text-anchor="${marker>14?'end':'start'}" fill="var(--muted)" font-size="8">观察起点</text>`;
 h+=`<path d="${M.smoothPath(values,x,y)}" fill="none" stroke="var(--accent)" stroke-width="1.45" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`;
 const last=values.at(-1);if(V(last))h+=`<circle cx="${x(rows.length-1)}" cy="${y(last)}" r="2" fill="var(--text)"/>`;
 return `<svg class="mini-chart" data-slots="${rows.length}" viewBox="0 0 240 69" role="img" aria-label="最近20个交易日收盘走势，非推荐后收益曲线">${h}</svg>`;
}
root.PrismCharts={chart,spark};
})(globalThis);
