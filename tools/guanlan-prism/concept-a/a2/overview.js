/* A.02 总览交互（仓库版）。移植自交付原型 overview-app.js，改动仅限：
 * 1) 业务口径（详评名单/方向更新/失效/观点标签/筛选）经由 PrismData 注入仓库规则，不再内置引擎；
 * 2) 页面骨架由壳层 render() 重建，因此全部事件用文档级委托、渲染入口暴露给 A2Hook；
 * 3) 星图页离开/返回时守卫骨架元素，动效只在 code:recDate 变化时播放一次。
 * 选择器与结论保持冻结上游数据，不新增研究判断。 */
(()=>{'use strict';
const M=PrismMath,C=PrismCharts,$=id=>document.getElementById(id),V=M.valid;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,d=2)=>V(v)?v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const pct=v=>V(v)?`${v>0?'+':''}${v.toFixed(2)}%`:'—';
const tone=v=>V(v)?v>0?'up':v<0?'down':'muted':'muted';
const md=d=>d?d.slice(5).replace('-',' / '):'—';
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
let D=null,raw=null;
const state={focus:0,record:0,mode:'line',metric:'amountYuan',period:5,motion:!reduced.matches,modal:null,modalMetric:'amountYuan',modalMode:'candle',focusAnimations:0,lastFocusKey:null,
 filters:{scope:'default',positive:false,opinion:'any'},query:'',journalDate:null,journalMode:'directions',
 recordsSort:{key:'formedOn',dir:-1},favorites:(()=>{try{return new Set(JSON.parse(localStorage.getItem('guanlan.a2.favorites')||'[]'))}catch{return new Set()}})()};
const motion=()=>state.motion&&!reduced.matches;
const group=()=>D?.deep[state.focus]||null,current=()=>group()?.records[state.record]||group()?.records[0]||null;
const policy=()=>raw.observationPolicy||{},daysOf=()=>{const p=policy();return V(p.primaryDays)?p.primaryDays:20},targetOf=()=>{const p=policy();return V(p.targetReturn)?p.targetReturn:.2};
const polar=(cx,cy,r,d)=>[cx+r*Math.cos(d*Math.PI/180),cy+r*Math.sin(d*Math.PI/180)];
const arc=(cx,cy,r,start,end)=>{let a=polar(cx,cy,r,start),b=polar(cx,cy,r,end);return `M${a.join(',')} A${r} ${r} 0 ${end-start>180?1:0} 1 ${b.join(',')}`};
function activityDial(s){
 const a=M.activity(D.history(s),state.period,'amountYuan'),factor=1e8,unit='亿元',label='成交量';
 const ratios=[a.ratio,a.previousRatio,1];const max= Math.max(2,Math.ceil(Math.max(...ratios.filter(V))*2)/2);
 let h='';
 for(let i=0;i<=54;i++){const deg=-135+270*i/54,p=polar(120,112,i%9===0?111:113,deg),q=polar(120,112,116,deg);h+=`<line x1="${p[0]}" y1="${p[1]}" x2="${q[0]}" y2="${q[1]}" stroke="var(--secondary)" opacity="${i%9===0?.5:.2}" stroke-width=".7"/>`}
 const layers=[{r:102,w:6,v:a.base,ratio:V(a.base)&&a.base>0?1:null,color:'#50565e',name:`前${state.period}日均值`},{r:89,w:11,v:a.previous,ratio:a.previousRatio,color:'#858b93',name:'前一交易日'},{r:72,w:22,v:a.today,ratio:a.ratio,color:'var(--text)',name:'本交易日'}];
 layers.forEach(l=>{h+=`<path d="${arc(120,112,l.r,-135,135)}" fill="none" stroke="#ffffff07" stroke-width="${l.w}"/>`;if(V(l.ratio)&&l.ratio>0)h+=`<path class="gauge-active" pathLength="1" d="${arc(120,112,l.r,-135,-135+270*l.ratio/max)}" fill="none" stroke="${l.color}" stroke-width="${l.w}"><title>${l.name} ${num(V(l.v)?l.v/factor:null)} ${unit}；基线的 ${num(l.ratio)} 倍</title></path>`});
 const one=polar(120,112,111,-135+270/max),two=polar(120,112,119,-135+270/max);
 if(V(a.base)&&a.base>0)h+=`<line x1="${one[0]}" y1="${one[1]}" x2="${two[0]}" y2="${two[1]}" stroke="var(--text)" stroke-width="1.5"/>`;
 h+=`<text x="120" y="110" text-anchor="middle" fill="var(--text)" style="font:32px var(--mono);letter-spacing:-1.5px">${num(V(a.today)?a.today/factor:null)}</text><text x="120" y="130" text-anchor="middle" fill="var(--muted)" font-size="9">今日${label} / ${unit}</text><text x="120" y="223" text-anchor="middle" fill="var(--muted)" style="font:8px var(--mono)">0 — ${max.toFixed(1)} ×</text>`;
 return `<article class="panel instrument volume-instrument"><div class="panel-heading"><div class="heading-main"><h3>成交活跃度</h3><div class="mini-tabs" aria-label="仪表指标"><button class="active" aria-pressed="true">成交量</button></div></div><span class="index">03 / ACTIVITY</span></div><div class="instrument-sub">同一刻度，比较今天、昨天与近期均值</div><div class="volume-tools"><div class="avg-tabs" aria-label="均值基线">${[5,10,20].map(n=>`<button data-period="${n}" class="${n===state.period?'active':''}" aria-pressed="${n===state.period}">${n}日</button>`).join('')}</div></div><div class="activity-body"><svg class="activity-dial" viewBox="0 0 240 230" role="img" aria-label="${label}三层同刻度仪表，今天${num(V(a.today)?a.today/factor:null)}${unit}，较前一交易日${pct(a.previousPct)}">${h}</svg><div class="activity-legend"><div class="value-line"><span><i class="swatch"></i>今天</span><strong>${num(V(a.today)?a.today/factor:null)}</strong></div><div class="value-line"><span><i class="swatch previous"></i>昨天</span><strong>${num(V(a.previous)?a.previous/factor:null)}</strong></div><div class="value-line"><span><i class="swatch average"></i>前${state.period}日均值</span><strong>${num(V(a.base)?a.base/factor:null)}</strong></div><div class="activity-separator"></div><div class="value-line"><span>较昨天</span><strong>${pct(a.previousPct)}</strong></div><span class="ratio-label">今天 / 前${state.period}日均值</span><div class="ratio">${num(a.ratio)} <small style="font-size:9px;color:var(--muted)">倍</small></div></div></div></article>`;
}
function observeDial(s){
 const n=D.daysObserved(s),days=daysOf();
 const known=V(n)&&V(days)&&days>0;
 const progress=known?Math.max(0,Math.min(1,n/days)):0;
 const valueAngle=180-180*progress;
 // 半圆观察仪表（布局评审稿 V1，参数锁定）：180° 上半圆厚环 + 外缘暗环 + 内外刻度
 // + 短针 + 白色半环轴心；中心(200,196)、主环半径158宽28、外暗环半径180宽22、针长44。
 const CX=200,CY=196;
 const P=(r,a)=>[CX+r*Math.cos(a*Math.PI/180),CY-r*Math.sin(a*Math.PI/180)];
 const arcPath=(r,a0,a1)=>{const p0=P(r,a0),p1=P(r,a1);
   return `M${p0[0].toFixed(3)},${p0[1].toFixed(3)} A${r},${r} 0 ${a0-a1>180?1:0} 1 ${p1[0].toFixed(3)},${p1[1].toFixed(3)}`};
 let h='';
 h+=`<path d="${arcPath(180,180,0)}" fill="none" stroke="#1c1d1f" stroke-width="22"/>`;
 for(let k=0;k<81;k++){const a=180-180*k/80,p1=P(179,a),p2=P(185,a);
   h+=`<line x1="${p1[0].toFixed(3)}" y1="${p1[1].toFixed(3)}" x2="${p2[0].toFixed(3)}" y2="${p2[1].toFixed(3)}" stroke="var(--muted)" stroke-width="1.6" stroke-linecap="round" opacity=".48"/>`}
 h+=`<path d="${arcPath(158,180,0)}" fill="none" stroke="#33363b" stroke-width="28"/>`;
 if(known&&progress>0)h+=`<path class="gauge-active" pathLength="1" d="${arcPath(158,180,valueAngle)}" fill="none" stroke="var(--text)" stroke-width="28"/>`;
 for(let k=1;k<=11;k++){const a=180-15*k,p1=P(141,a),p2=P(151,a);
   const onWhite=known&&a>valueAngle;
   h+=`<line x1="${p1[0].toFixed(3)}" y1="${p1[1].toFixed(3)}" x2="${p2[0].toFixed(3)}" y2="${p2[1].toFixed(3)}" stroke="${onWhite?'#111112':'#aaaeb2'}" stroke-width="2.1" stroke-linecap="round"/>`}
 h+=`<text x="200" y="132" text-anchor="middle" fill="var(--text)" style="font:68px var(--mono);letter-spacing:-2px">${V(n)?String(n).padStart(2,'0'):'—'}</text>`;
 h+=`<path d="M9 196H56 M344 196H391" stroke="var(--muted)" stroke-width="1.1"/>`;
 h+=`<path d="M178,196 A22,22 0 0 1 222,196 L211,196 A11,11 0 0 0 189,196 Z" fill="var(--text)"/>`;
 if(known){const tip=P(44,valueAngle);
   h+=`<g class="armory-needle" style="--needle-start:${(-180*progress).toFixed(3)}deg;transform-origin:200px 196px"><line x1="200" y1="196" x2="${tip[0].toFixed(3)}" y2="${tip[1].toFixed(3)}" stroke="#0b0c0e" stroke-width="4.5" stroke-linecap="round"/><line x1="200" y1="196" x2="${tip[0].toFixed(3)}" y2="${tip[1].toFixed(3)}" stroke="var(--text)" stroke-width="1.6" stroke-linecap="round"/></g>`}
 const label=known?`已观察${n}个交易日，窗口${days}日，指针指向当前进度`:'观察天数暂缺';
 return `<article class="panel instrument observe-instrument"><div class="panel-heading"><h3>观察进度</h3><span class="index">01 / DURATION</span></div><div class="instrument-sub">知道看到哪里，也从哪里开始</div><div class="observe-body armory-body"><svg class="observe-dial armory-dial" viewBox="0 0 400 208" role="img" aria-label="${label}">${h}</svg><div class="armory-stats"><div><b>${md(s.formedOn||s.recDate)}</b><span>本次${s.formedOn?'推荐':'入选'}</span></div><div><b>${num(s.ref)}</b><span>原参考价 / 元</span></div></div></div></article>`;
}
function judgment(s){
 const daily=new Map();D.ordered(s).forEach(r=>daily.set(r.date,r));const rows=[...daily.values()].slice(-7),r=rows.at(-1),dir=D.direction(r),label=dir?D.dirLabels[dir]:'方向未识别';let h='';
 const x=i=>63+(i+.5)*278/Math.max(7,rows.length),ys={up:28,sideways:64,down:100};
 for(const [code,y] of Object.entries(ys))h+=`<text x="42" y="${y+3}" text-anchor="end" fill="var(--muted)" font-size="8">${D.dirLabels[code]}</text><line x1="55" y1="${y}" x2="346" y2="${y}" stroke="var(--line)" stroke-dasharray="2 5"/>`;
 rows.forEach((r,i)=>{const d=D.direction(r),yy=ys[d]??118,last=i===rows.length-1;h+=`<g class="review-node" tabindex="0" role="button" data-review-date="${r.date}" aria-label="查看${r.date}原复盘，${D.dirLabels[d]||'方向未识别'}"><line x1="${x(i)}" y1="122" x2="${x(i)}" y2="${yy}" stroke="var(--secondary)" opacity="${last?.8:.35}"/><circle cx="${x(i)}" cy="${yy}" r="${last?4:2.8}" fill="${d?'var(--text)':'var(--panel)'}" stroke="var(--secondary)" stroke-width="1"/><text x="${x(i)}" y="139" text-anchor="middle" fill="var(--muted)" style="font:7.5px var(--mono)">${r.date.slice(5).replace('-','/')}</text><title>${esc(r.base||'方向未识别')}</title></g>`});
 if(!rows.length)h+=`<text x="206" y="72" text-anchor="middle" fill="var(--muted)" font-size="10">尚无保存的复盘</text>`;
 return `<article class="panel instrument judgment-instrument"><div class="panel-heading"><h3>近期复盘判断</h3><span class="index">02 / OUTLOOK</span></div><div class="instrument-sub">从已有复盘看变化，不再重复画价格</div><div class="judgment-heading"><b>${label}</b><span>最新 · 未来 1—3 个交易日</span></div><svg class="judgment-chart" viewBox="0 0 360 148" role="img" aria-label="最近${rows.length}次保存的短期方向，点击圆点读原文">${h}</svg><div class="instrument-footer"><span>点圆点读原文 ↗</span></div></article>`;
}
function drawWidgets(animate=false){if(!$('instruments'))return;const s=current();if(!s)return;$('instruments').innerHTML=observeDial(s)+judgment(s)+activityDial(s);if(animate&&motion()){$('instruments').firstElementChild.classList.toggle('is-entering',D.key(s)!==state.lastFocusKey);document.querySelectorAll('.gauge-active').forEach((p,i)=>{p.style.strokeDasharray='1';p.animate([{strokeDashoffset:'1'},{strokeDashoffset:'0'}],{duration:850+i*80,easing:'cubic-bezier(.2,.65,.3,1)'})})}}
function relativeRows(s,rows){return [{name:s.name,color:'var(--text)',values:D.comparison(s,'stock')},{name:s.industryName||'行业对照',color:'var(--blue)',values:D.comparison(s,'industry')},{name:raw.market_name||'市场对照',color:'var(--amber)',values:D.comparison(s,'market')}].map(series=>({...series,values:rows.map(r=>r.date?series.values[D.sessions.indexOf(r.date)]??null:null)}))}
function renderHeroChart(animate=false){const s=current();if(!s||!$('heroPlot'))return;const rows=M.windowRows(D.history(s),D.sessions,D.end,40);const hasRef=!s.d0&&s.recDate<=D.end&&V(s.ref);const rel=relativeRows(s,rows);
 C.chart($('heroPlot'),{rows,mode:state.mode,relative:rel,reference:hasRef?s.ref:null,target:hasRef?s.ref*(1+targetOf()):null,recDate:s.recDate,metric:'amountYuan',name:s.name,fullHistory:D.history(s),animate,motion:motion()});
 const dates=rows.filter(r=>r.date);$('chartRange').innerHTML=`最近 <strong>40</strong> 个交易日 · ${dates[0]?.date||'—'} — ${D.end} <span class="muted">${rows.filter(r=>V(r.close)).length}/40 日有价格</span>`;
 let legend=state.mode==='relative'?`<span><i class="own"></i>个股</span><span><i class="industry"></i>${esc(s.industryName||'行业对照')}</span><span><i class="benchmark"></i>${esc(raw.market_name||'市场对照')}</span>`:state.mode==='candle'?`<span><i></i>MA5</span><span><i class="industry"></i>MA10</span><span><i class="benchmark"></i>MA20</span><span>红：收 ≥ 开　绿：收 &lt; 开</span>`:`<span><i></i>收盘价</span><span><i class="reference"></i>原参考价</span><span><i class="target"></i>原观察目标</span>`;
 $('chartLegend').innerHTML=legend;$('chartPolicy').textContent=state.mode==='relative'?'基准固定为首个观察日收盘＝100；与较参考价涨跌口径不同。':state.mode==='candle'?'真实开高低收 · 右轴价格 · 鼠标或左右键查看逐日数值':'圆滑连接实际收盘点，不改原始数值 · 每5个交易日标注日期';
 if(state.mode==='relative'&&!rel[0].values.some(V))$('chartPolicy').textContent='首个观察日收盘暂缺，不能换基准计算相对走势。';
 if(animate&&motion())state.focusAnimations++;
}
function renderFocus(animate=true){if(!$('focusContent'))return;const s=current();
 if(!s){$('focusContent').innerHTML='<div class="panel empty-state">当天没有普通详评记录；不从其他股票补位。</div>';$('stockSelect').disabled=true;$('prevFocus').disabled=$('nextFocus').disabled=true;return}
 $('stockSelect').innerHTML=D.deep.map((g,i)=>`<option value="${i}">${esc(g.records[0].name)}</option>`).join('');
 $('focusName').textContent=s.name;$('stockSelect').value=String(state.focus);$('focusCount').textContent=`${String(state.focus+1).padStart(2,'0')} / ${String(D.deep.length).padStart(2,'0')}`;
 const r=D.latest(s),dir=D.direction(r),q=D.quote(s);const g=group();const recordSelect=g.records.length>1?`<select id="episodeSelect" aria-label="同股不同推荐记录">${g.records.map((x,i)=>`<option value="${i}" ${i===state.record?'selected':''}>${x.recDate} 开始观察</option>`).join('')}</select>`:'';
 $('focusContent').innerHTML=`<div class="instruments" id="instruments"></div><article class="panel hero-chart"><div class="chart-heading"><div><h3>${esc(s.name)} <span class="num ${tone(D.ret(s))}">${pct(D.ret(s))}</span></h3><p>${esc(s.code)} · 收盘 ${num(q.close)} 元 · 原参考价 ${num(s.ref)} 元 · 价格涨跌（未复权） · 第 ${D.daysObserved(s)??'—'} / ${daysOf()} 个交易日</p></div><div class="chart-tabs" role="group" aria-label="主图模式">${[['line','收盘走势'],['relative','相对走势'],['candle','K 线']].map(([mode,label])=>`<button data-chart-mode="${mode}" class="${mode===state.mode?'active':''}" aria-pressed="${mode===state.mode}">${label}</button>`).join('')}</div></div><div class="chart-context"><span id="chartRange"></span>${recordSelect}</div><div id="heroPlot" class="chart-host"></div><div class="chart-foot"><div class="legend" id="chartLegend"></div><span id="chartPolicy"></span></div><div class="chart-note"><div class="note-tags">${opTag(s)}<span class="tag">未来 1—3 日 · ${dir?D.dirLabels[dir]:'未识别状态'}</span></div><p>${esc(r?.viewReason||r?.outlookReason||'尚无复盘原文。')}</p></div></article>`;
 const changed=D.key(s)!==state.lastFocusKey;drawWidgets(animate&&changed);renderHeroChart(animate&&changed);state.lastFocusKey=D.key(s);
}
function setFocus(i,record=0){if(!D||!D.deep.length)return;const next=(i+D.deep.length)%D.deep.length;const s=D.deep[next].records[record]||D.deep[next].records[0];if(D.key(s)===state.lastFocusKey&&next===state.focus&&record===state.record)return;state.focus=next;state.record=record;renderFocus(true)}
function markets(){if(!$('marketStrip'))return;const rows=D.markets();$('marketStrip').innerHTML=rows.map((m,i)=>{const fresh=m.trade_date===D.end,change=fresh&&V(m.close)&&V(m.previousClose)&&m.previousClose>0?(m.close/m.previousClose-1)*100:null;const series=(fresh?m.series||[]:[]).slice(-20).map(close=>({close}));return `<button class="market-card" data-index="${i}" aria-label="查看${esc(m.name)}最近50个交易日K线"><span class="market-name">${esc(m.name)} <small>${esc(m.code)}</small></span><span class="market-arrow">↗</span><div class="market-value">${num(fresh?m.close:null)}</div><div class="market-change ${tone(change)}">${pct(change)}</div>${series.length>=2?C.spark(series):''}</button>`}).join('')}
function cards(){if(!$('stockRail'))return;const list=D.recommendations.filter(s=>!D.invalid(s));$('recordCount').textContent=`${list.length} 条记录 · 同股不同推荐分别保留`;$('recordNote').textContent=`按入选日期由近到远 · 已隐藏 ${D.recommendations.length-list.length} 条判断失效记录 · 小图固定为最近20个交易日，不是推荐后的收益曲线。`;
 $('stockRail').innerHTML=list.length?list.map(s=>{const q=D.quote(s),r=D.ret(s),rows=M.windowRows(D.history(s),D.sessions,D.end,20);return `<button class="panel stock-card" data-stock="${esc(D.key(s))}" aria-label="查看${esc(s.name)}这次推荐"><h3>${esc(s.name)}<span>↗</span></h3><span class="code">${esc(s.code)}</span><div class="price-row"><b>${num(q.close)}</b><span class="${tone(r)}">${pct(r)}</span></div><div class="price-label"><span>当日收盘 / 元</span><span>价格涨跌（未复权）</span></div>${opTag(s)}<div class="recent-label">最近 20 个交易日</div>${C.spark(rows,{markDate:s.recDate})}<div class="card-foot"><span>${s.d0?'待首日观察':`已观察 ${D.daysObserved(s)??'—'} 天`}</span><span>${s.formedOn?'推荐':'入选'} ${md(s.formedOn||s.recDate)}</span></div></button>`}).join(''):'<div class="panel empty-state">暂无未失效的推荐记录。</div>';
 $('updatesCount').textContent=`${D.updates.length} 条更新 · 桌面每屏 3 条`;
 $('updatesRail').innerHTML=D.updates.length?D.updates.map((u,i)=>`<button class="panel update-card" data-update="${i}" aria-label="查看${esc(u.s.name)}观点更新原文"><div class="update-title"><h3>${esc(u.s.name)}</h3><time>${md(u.r.date)}</time></div><div class="transition"><b>${D.dirLabels[u.from]}</b><span>→</span><b>${D.dirLabels[u.to]}</b><span style="margin-left:auto;font-size:8px">未来 1—3 日</span></div><p>${esc(u.reason||'原文未提供变化原因。')}</p><div class="read-link"><span>原复盘对照</span><span>读完整记录 ↗</span></div></button>`).join(''):'<div class="panel empty-state">今天没有可识别的方向切换，不填充占位股票。</div>';
 setupRail('stockRail','stockScroll','stockPosition');setupRail('updatesRail','updatesScroll','updatesPosition');
}
function setupRail(id,inputId,labelId){const rail=$(id),input=$(inputId);if(!rail||!input)return;let busy=false;
 const sync=()=>{const max=rail.scrollWidth-rail.clientWidth;input.disabled=max<=1;input.value=max>0?String(Math.round(rail.scrollLeft/max*1000)):'0';const first=rail.firstElementChild;const step=first?first.getBoundingClientRect().width+14:1;const page=Math.max(1,Math.round(rail.clientWidth/step)),start=Math.round(rail.scrollLeft/step)+1,total=rail.querySelectorAll('button').length;$(labelId).textContent=total?`${start}–${Math.min(total,start+page-1)} / ${total}`:'0 / 0';document.querySelectorAll(`[data-rail="${id}"]`).forEach(b=>b.disabled=Number(b.dataset.step)<0?rail.scrollLeft<2:rail.scrollLeft>=max-2)};
 input.addEventListener('input',()=>{rail.scrollLeft=Number(input.value)/1000*(rail.scrollWidth-rail.clientWidth)});rail.addEventListener('scroll',()=>{if(!busy){busy=true;requestAnimationFrame(()=>{busy=false;sync()})}},{passive:true});rail._sync=sync;sync();
}
// Native dialog supplies focus containment. Motion only changes the window, never quote values.
const dialog=$('detailDialog'),win=dialog.querySelector('.modal-window');let origin=null,closing=false,openingAnimation=null,previousOverflow='';
function openWindow(target,reading=false){if(!dialog.open)origin=target?.getBoundingClientRect?target:null;closing=false;win.classList.toggle('reading',reading);$('chartTooltip').hidden=true;dialog.appendChild($('chartTooltip'));if(!dialog.open)previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';if(!dialog.open)dialog.showModal();$('closeDialog').focus({preventScroll:true});
 if(motion()){const b=win.getBoundingClientRect(),a=origin?.getBoundingClientRect();const transform=a?`translate(${a.left+a.width/2-b.left-b.width/2}px,${a.top+a.height/2-b.top-b.height/2}px) scale(${Math.max(.08,a.width/b.width)},${Math.max(.08,a.height/b.height)})`:'translateY(18px) scale(.96)';openingAnimation=win.animate([{transform,opacity:.12},{transform:'translate(0,0) scale(1,1)',opacity:1}],{duration:340,easing:'cubic-bezier(.16,1,.3,1)'})}}
async function closeWindow(){if(!dialog.open||closing)return;closing=true;$('chartTooltip').hidden=true;openingAnimation?.cancel();
 if(motion()){const b=win.getBoundingClientRect(),a=origin?.getBoundingClientRect();const transform=a?`translate(${a.left+a.width/2-b.left-b.width/2}px,${a.top+a.height/2-b.top-b.height/2}px) scale(${Math.max(.08,a.width/b.width)},${Math.max(.08,a.height/b.height)})`:'translateY(15px) scale(.96)';try{await win.animate([{transform:'translate(0,0) scale(1,1)',opacity:1},{transform,opacity:0}],{duration:240,easing:'cubic-bezier(.4,0,.6,1)',fill:'forwards'}).finished}catch{}}
 win.getAnimations().forEach(a=>a.cancel());dialog.close();document.body.style.overflow=previousOverflow;document.body.appendChild($('chartTooltip'));state.modal=null;closing=false;if(origin?.isConnected)origin.focus({preventScroll:true})}
function modalTitle(name,code,caption){$('modalTitleBlock').innerHTML=`<h2 id="dialogTitle">${esc(name)} <small>${esc(code)}</small></h2><p>${esc(caption)}</p>`}
const introStamp=t=>{const s=String(t||'');return /^\d{4}-\d{2}-\d{2}T/.test(s)?s.slice(0,16).replace('T',' '):s};
const safeHref=u=>typeof u==='string'&&/^https?:\/\//i.test(u)?u:null;
function introTable(tbl){
 if(!tbl||!Array.isArray(tbl.columns)||!Array.isArray(tbl.rows))return '';
 const head=tbl.columns.map(c=>'<th>'+esc(c)+'</th>').join('');
 const body=tbl.rows.map(r=>'<tr>'+r.map(c=>'<td>'+esc(c)+'</td>').join('')+'</tr>').join('');
 const note=tbl.note?'<p class="intro-table-note">'+esc(tbl.note)+'</p>':'';
 return `<div class="intro-table-wrap"><table class="intro-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${note}`;
}
function companyTabBody(s){
 const intro=s.companyIntroduction;
 if(intro&&Array.isArray(intro.sections)&&intro.sections.length){
  const cut=introStamp(intro.as_of);
  const gen=introStamp(intro.generated_at);
  const secs=intro.sections.map(sec=>{
   const paras=(sec.paragraphs||[]).map(p=>'<p>'+esc(p)+'</p>').join('');
   const refs=(sec.source_ids||[]).length?`<span class="intro-refs">${sec.source_ids.map(id=>'['+esc(id)+']').join(' ')}</span>`:'';
   return `<section class="intro-section"><h4>${esc(sec.title)}${refs}</h4>${paras}${introTable(sec.table)}</section>`;
  }).join('');
  const sources=(intro.sources||[]).map(src=>{
   const href=safeHref(src.url);
   const link=href?` <a href="${esc(href)}" target="_blank" rel="noopener noreferrer">原文</a>`:'';
   const meta=src.kind==='warehouse'
     ?`本地事实仓 · ${esc(src.dataset||'')}${src.report_period?' · 报告期 '+esc(src.report_period):''}`
     :`${src.evidenceAvailable?'已留存官方原文':'历史官方引用（原文未留存）'} · 公开依据：${esc(src.availability_basis||'')}${src.retrieved_at?' · 实际补读 '+esc(introStamp(src.retrieved_at)):''}`;
   return `<li><b>${esc(src.id)}</b> ${esc(src.title||'')}<span class="intro-src-meta">${meta} · 可用 ${esc(introStamp(src.available_at))}${src.locator?' · '+esc(src.locator):''}</span>${link}</li>`;
  }).join('');
  const lims=(intro.limitations||[]).length?`<div class="intro-limit"><h4>资料限制</h4><ul>${intro.limitations.map(l=>'<li>'+esc(l)+'</li>').join('')}</ul></div>`:'';
  const back=introStamp(intro.as_of)!==gen?`，实际编写于 ${esc(gen)}`:'';
  return `<div class="review-meta"><span>COMPANY PROFILE · 推荐时点资料</span><span>资料截至 ${esc(cut)}</span></div><h3>${esc(s.name)}</h3><div class="intro-body">${secs}${lims}${sources.length?`<details class="intro-sources"><summary>资料来源（${(intro.sources||[]).length}）</summary><ul>${sources}</ul></details>`:''}<p class="source-hint">本篇介绍只使用推荐研究截止（${esc(cut)}）前能取得的公开资料${back}；覆盖文中列出的来源，不表示核验了全部公告，也不构成新的买卖建议。</p></div>`;
 }
 if(s.company)return `<div class="review-meta"><span>COMPANY PROFILE</span><span>${esc((raw.sourceInfo?.label||'本地归档'))}</span></div><h3>${esc(s.name)}</h3><div class="copy"><p>${esc(s.company)}</p></div><p class="source-hint">旧快照中的简要资料；完整推荐时点介绍暂缺。</p>`;
 return `<div class="review-meta"><span>COMPANY PROFILE</span><span>暂缺</span></div><h3>${esc(s.name)}</h3><div class="copy"><p>这次推荐的完整公司介绍暂未生成。</p></div><p class="source-hint">介绍缺失是资料暂缺，不代表公司经营变化。</p>`;
}
function finalReviewBody(r){
 const f=r?.finalTwentyDayReview;if(!f)return '';
 const m=f.metrics||{};
 const facts=[["D20收盘",m.d20_close_return_since_entry],["期间最高收盘",m.d20_max_close_return_since_entry],["期间最深下跌",m.d20_mae_since_entry]].map(([label,value])=>label+"："+(value==null?"数据不足":(value*100).toFixed(2)+"%")).join("；");
 return `<section class="final-review"><h4>20个交易日固定结案</h4><p>${esc(f.final_twenty_day_review.overall_review)}</p><p>${esc(facts)}</p><p class="source-hint">原结论保存：${esc(f.analysis_date)} · 截止 ${esc(f.as_of)}</p></section>`;
}
const paragraphs=value=>String(value||'').split(/\n\s*\n/).filter(Boolean).map(p=>`<p class="original-copy">${esc(p)}</p>`).join('');
function statementInline(value){
 const text=String(value||'');let out='',last=0;
 const tokens=/\[([^\]\n]+)\]\((?:<([^>\n]+)>|([^\)\n]+))\)|\*\*([^*]+)\*\*/g;
 for(const m of text.matchAll(tokens)){
  out+=esc(text.slice(last,m.index));
  if(m[4])out+=`<strong>${esc(m[4])}</strong>`;
  else{const href=safeHref(m[2]||m[3]);out+=href?`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(m[1])}</a>`:esc(m[1])}
  last=m.index+m[0].length;
 }
 return out+esc(text.slice(last));
}
const statementParagraphs=value=>String(value||'').split(/\n\s*\n/).filter(Boolean).map(p=>{
 const lines=p.split('\n');
 if(lines.every(l=>/^\s*[-*] /.test(l)))return `<ul class="original-copy">${lines.map(l=>`<li>${statementInline(l.replace(/^\s*[-*] /,''))}</li>`).join('')}</ul>`;
 return `<p class="original-copy">${statementInline(p).replace(/\n/g,'<br>')}</p>`;
}).join('');
function trackingNotice(s,day){
 const exit=s.trackingExitDate;
 if(!exit){return day===D.end&&s.trackingStatus==='evaluation_only'?'<section class="tracking-notice reading-note"><h3>已停止主动跟踪</h3><p>原记录缺少停止日期，停止原因需核对后展示。</p></section>':''}
 if(day<exit)return '';
 const prior=(s.reviews||[]).filter(r=>r.date<=day&&r.date<=exit).sort((a,b)=>a.date.localeCompare(b.date)).at(-1);
 const closed=(s.reviews||[]).some(r=>r.date<=day&&r.finalTwentyDayReview);
 const note=closed?'D20 固定结案已保存，可切换到结案日查看。':'停止后不再写普通每日复盘；仍保留价格观察和 D20 固定结案。';
 return `<section class="tracking-notice reading-note"><h3>已停止主动跟踪 · ${esc(exit)}</h3><p>${esc(s.trackingExitReason||'原记录未保存停止原因，待补充。')}</p><p>${note}</p>${prior?`<button class="text-button" data-stock="${esc(D.key(s))}" data-date="${esc(prior.date)}" data-tab="review">查看停止前最后一篇复盘（${esc(prior.date)}） →</button>`:''}</section>`;
}
function formalReturnAt(s,day){
 if(s.d0||!V(s.ref)||s.ref<=0||day<s.recDate)return null;
 const value=(s.reviews||[]).find(r=>r.date===day)?.formalReturn;
 if(V(value))return value*100;
 return s.formalReturnDate===day&&V(s.formalReturn)?s.formalReturn*100:null;
}
function returnBasis(s,day){
 return `<p class="return-basis">价格涨跌（未复权）：${pct(retAtDate(s,day))} · 复盘涨跌（复权）：${pct(formalReturnAt(s,day))}<br><span class="muted">都相对本次观察起点；复盘使用复权价格，分红送转可能使两者不同。缺少同日数据时显示“—”。</span></p>`;
}
function originalBody(s){
 const hasFull=Boolean(String(s.statementFull||'').trim());
 const note=hasFull?(s.statementSource==='adopted_rewrite'?'用户认可的表达范本（后续修订稿）；原正式推荐记录不改写。':s.statementSource==='verified_recommendation'?'原回复的推荐分区已独立核对；整份合并日报尚未完成验收。':s.statementSource==='legacy_daily_report'?'已核对原推荐身份的历史日报原文。':'推荐形成日日报中的逐股原文。'):'历史摘要仅供核对，不能代替完整推荐论证。';
 const body=hasFull?statementParagraphs(s.statementFull):`<p class="reading-note">${esc(s.statementNote||'尚缺完整推荐正文：原推荐的完整正文尚未归档，暂显示历史摘要。')}</p>`;
 const summary=hasFull?'':`<h4>原推荐理由摘要</h4>${paragraphs(s.reasonFull)||'<p>原推荐理由暂缺。</p>'}`;
 return `<h3>当初为什么选它</h3>${body}<details class="original-summary"><summary>${hasFull?'查看原记录风险摘要':'查看历史记录摘要（非完整正文）'}</summary>${summary}<h4>原推荐中的风险</h4>${paragraphs(s.reasonRisk)||'<p>原记录未附风险文字。</p>'}</details><p class="reading-note">${note} 推荐形成日：${esc(s.formedOn||'未提供')}。切换日期不会改写原推荐理由。</p>`;
}
function fullReview(s,r,day=r?.date||state.modal?.date||D.end){
 const stop=trackingNotice(s,day);
 if(!r)return stop||'<p>所选日期没有保存复盘正文。可切换日期查看已有记录；不把旧复盘当作当天结论。</p>';
 const o=r.currentOpportunity;
 const copy=String(r.copy||r.summary_copy||'').split(/\n\s*\n/).filter(Boolean);
 if(copy[0]===r.headline)copy.shift();
 return `${stop}<section class="full-review" data-review-date-text="${esc(r.date)}"><h3>${esc(r.headline||'原复盘')} · ${esc(r.date)}</h3><p>${esc(kindLabel(r))} · 第 ${esc(r.day)} 天 · ${esc(r.viewLabel||'观点标签暂缺')}</p>${paragraphs(copy.join('\n\n'))||'<p>本条复盘正文暂缺。</p>'}
 ${r.base?`<h3>未来 1—3 日</h3>${paragraphs(r.base)}${paragraphs(r.outlookReason)}`:''}
 ${r.confirm?`<h3>进一步支持当前方向的表现</h3>${paragraphs(r.confirm)}`:''}
 ${r.risk?`<h3>会让我改变判断的表现</h3>${paragraphs(r.risk)}`:''}
 ${r.viewReason?`<h3>与前次判断比较</h3>${paragraphs(r.viewReason)}`:''}
 ${o?`<section class="current-opportunity"><h3>未来 5—10 日 · 当前参与意见</h3>${paragraphs(o.directionText)}${paragraphs(o.outlookReason)}${paragraphs(o.participationText)}${paragraphs(o.participationReason)}<h4>改变判断的条件</h4>${paragraphs(o.changeCondition)}<p>参考收盘：${num(o.referenceClose)} 元 · ${esc(o.referenceDate||'未提供')}</p></section>`:''}
 ${returnBasis(s,r.date)}${finalReviewBody(r)}${(s.dataIssues||[]).filter(x=>!x.reviewDate||x.reviewDate===r.date).map(x=>`<p class="reading-note">${esc(x.message)}</p>`).join('')}
 <p class="reading-note">原文按保存内容展示。记录截止：${esc(r.as_of||'原记录未提供')}。</p></section>`;
}
function stockNav(){
 const m=state.modal,s=m.item;const dates=D.sessions.filter(d=>d>=s.recDate||s.d0);
 if(!dates.includes(m.date))dates.push(m.date);dates.sort();
 return `<div class="stock-detail-nav"><nav class="mini-tabs" aria-label="个股阅读内容">${[['chart','走势'],['review','完整复盘'],['original','当初为什么选它'],['company','公司资料']].map(([id,label])=>`<button data-detail-tab="${id}" class="${m.tab===id?'active':''}" aria-pressed="${m.tab===id}">${label}</button>`).join('')}</nav><label>查看日期 <select id="detailDate" aria-label="个股查看日期">${dates.map(d=>`<option value="${d}" ${d===m.date?'selected':''}>${d}${s.reviews.some(r=>r.date===d)?' · 有复盘':''}</option>`).join('')}</select></label></div>`;
}
function drawModalChart(){
 const modal=state.modal;if(!modal||!['index','stock'].includes(modal.type))return;
 const isIndex=modal.type==='index',item=modal.item,end=isIndex?D.end:modal.date;
 const history=(isIndex?D.indexHistory(item):D.history(item)).filter(r=>r.date<=end);
 const review=isIndex?null:D.ordered(item).find(r=>r.date===end);
 const reading=!isIndex&&modal.tab!=='chart';win.classList.toggle('reading',reading);
 if(!isIndex)modalTitle(item.name,item.code,`${item.recDate} 开始观察 · 查看 ${end}`);
 if(reading){
  const body=modal.tab==='company'?companyTabBody(item):modal.tab==='original'?originalBody(item):fullReview(item,review,end);
  $('dialogContent').innerHTML=stockNav()+`<div class="reading-body">${body}</div>`;
  $('modalFooter').textContent=modal.tab==='company'?'公司资料固定于原推荐时点；不随查看日期更新':'按现有归档阅读；不重新生成研究结论';return;
 }
 const rows=M.windowRows(history,D.sessions,end,isIndex?50:40),q=rows.at(-1),available=rows.filter(r=>[r.open,r.high,r.low,r.close].every(V)).length;
 const ratio=V(q.close)&&V(rows.at(-2).close)&&rows.at(-2).close>0?(q.close/rows.at(-2).close-1)*100:null;
 // 个股弹窗与首页主图同构：三种模式可切、量度固定为成交额（按钮沿用「成交量」叫法）；指数弹窗保持 K 线 + 量额切换。
 const mode=isIndex?'candle':state.modalMode;
 const toolRight=isIndex
  ?`<div class="mini-tabs"><button data-modal-metric="volumeShares" class="${state.modalMetric==='volumeShares'?'active':''}">成交量</button><button data-modal-metric="amountYuan" class="${state.modalMetric==='amountYuan'?'active':''}">成交额</button></div>`
  :`<div class="chart-tabs" role="group" aria-label="主图模式">${[['line','收盘走势'],['relative','相对走势'],['candle','K 线']].map(([m,label])=>`<button data-modal-mode="${m}" class="${state.modalMode===m?'active':''}" aria-pressed="${state.modalMode===m}">${label}</button>`).join('')}</div>`;
 const legend=isIndex||mode==='candle'
  ?`<span><i></i>MA5</span><span><i class="industry"></i>MA10</span><span><i class="benchmark"></i>MA20</span><span>红：收 ≥ 开　绿：收 &lt; 开</span>`
  :mode==='relative'
  ?`<span><i></i>个股</span><span><i class="industry"></i>${esc(item.industryName||'行业对照')}</span><span><i class="benchmark"></i>${esc(raw.market_name||'市场对照')}</span>`
  :`<span><i></i>收盘价</span><span><i class="reference"></i>原参考价</span><span><i class="target"></i>原观察目标</span>`;
 const footRight=mode==='candle'?`每5个交易日标日期 · ${available}/${rows.length} 日有完整 K 线`
  :mode==='relative'?'基准固定为首个观察日收盘＝100':`每5个交易日标日期 · ${rows.filter(r=>V(r.close)).length}/${rows.length} 日有价格`;
 $('dialogContent').innerHTML=(isIndex?'':stockNav())+`<div class="modal-toolbar"><div class="summary"><strong class="market-big">${num(q.close)}</strong><span class="${tone(ratio)}">${pct(ratio)}</span><span>· 截至 ${end} 收盘</span></div>${toolRight}</div><div id="modalChart" class="chart-host modal-chart"></div><div class="chart-foot"><div class="legend">${legend}</div><span>${footRight}</span></div>${!isIndex?`<div class="chart-note">${trackingNotice(item,end)}${returnBasis(item,end)}<p>${esc(review?.viewReason||review?.outlookReason||'所选日期没有复盘原文。')}</p><button class="text-button" data-detail-tab="review">阅读完整复盘 →</button></div>`:''}`;
 const showRef=!isIndex&&!item.d0&&end>=item.recDate;
 C.chart($('modalChart'),{rows,mode,reference:showRef?item.ref:null,target:showRef&&V(item.ref)?item.ref*(1+targetOf()):null,recDate:isIndex?null:item.recDate,metric:isIndex?state.modalMetric:'amountYuan',relative:!isIndex?relativeRows(item,rows):[],name:item.name,fullHistory:history,isIndex:true,animate:false,motion:motion()});
 $('modalFooter').textContent=isIndex?'最近50个交易日 · 指数点位与成交':`按当前冻结数据截取至 ${end}；不代表重新取得当时快照`;
}
function openIndex(i,target){const item=D.markets()[i];state.modal={type:'index',item};state.modalMetric='amountYuan';modalTitle(item.name,item.code,'最近 50 个交易日 · K 线与成交 · 点击图表或移动鼠标查看每日价格');$('dialogContent').innerHTML='<div style="height:56vh"></div>';openWindow(target);drawModalChart();}
function openStock(key,target,date=null,tab='chart'){
 ensureData();const item=raw.stocks.find(s=>D.key(s)===key);if(!item)return;
 state.modal={type:'stock',item,date:date||D.end,tab};
 modalTitle(item.name,item.code,`${item.recDate} 开始观察`);$('dialogContent').innerHTML='';
 openWindow(target,tab!=='chart');drawModalChart();
}
function openReview(s,r,previous,target){
 if(!r)return;state.modal={type:'review'};modalTitle(s.name,'原复盘',`${r.date} · 本次观察 ${s.recDate} 开始`);
 $('dialogContent').innerHTML=`<div class="reading-body">${previous?'<h3>前一次</h3>'+fullReview(s,previous):''}<h3>这一次</h3>${fullReview(s,r)}<button class="text-button" data-stock="${esc(D.key(s))}" data-date="${esc(r.date)}" data-tab="review">查看这次推荐详情 →</button></div>`;
 $('modalFooter').textContent='展示原复盘，不生成新结论';openWindow(target,true);
}
function openNotes(target){state.modal={type:'notes'};modalTitle('A2 使用说明','AFTERCLOSE','本地正式研究结果 · 主用展示');$('dialogContent').innerHTML=`<div class="reading-body"><h3>01　成交量与成交额分开</h3><p>右侧C形表盘：白色粗环是今天，灰色环是前一交易日，外圈是前5/10/20日均值。三个环共享角度刻度。均值不含今天；底部显示实际有效日数。较昨天是相邻交易日比较，不称同比。</p><h3>02　40日主图，只在换股票时动一次</h3><p>收盘与相对曲线使用保单调三次插值，经过原始每日点且不产生额外高低点。窗口固定最近40个交易日，每5个交易日标日期。重复选中同一记录、滚动、调整尺寸和切图表模式均不重播。</p><h3>03　价格明确的K线</h3><p>开高低收、右轴价格、最新收盘、窗口极值、MA5/10/20及成交栏可同屏查看。鼠标与方向键读取原始值。K线本身不做曲线平滑。价格涨跌使用未复权报价；正式复盘使用复权价格，分红送转可能造成差异，两种口径在详情中分开展示。</p><h3>04 / 05　清单和观点更新分成两排</h3><p>推荐清单占整行，小图固定最近20个交易日，观察起点有标记。观点更新在下一行，桌面每屏3张、手机1张，不截断原原因。</p><h3>06　指数近屏幕大小弹窗</h3><p>点击指数展开50个交易日K线，窗口从卡片位置展开、向原位置收回。点击空白、关闭按钮或Esc均可收起。缺开高低收时保持缺失，不从收盘折线伪造K线。</p><h3>07　图9改为近期复盘判断</h3><p>只使用已保存的短期方向，分上涨、横盘、下跌三个类别，点圆点看原文。不造“信心分”“爆发概率”等指标。</p><p class="reading-note">本页随正式研究归档更新。走势按所选日期截断；完整复盘按原文展示，公司资料固定在原推荐时点。旧版只作停更备用。</p></div>`;$('modalFooter').textContent='只展示本地已归档研究内容';openWindow(target,true);}
function renderAll(animate){markets();renderFocus(animate);cards()}
function ensureData(){if(D)return;raw=JSON.parse($('snapshot').textContent);let extra={};try{extra=JSON.parse($('preview-series').textContent||'null')||{}}catch(e){extra={}}
 try{D=PrismData.create(raw,extra,window.GuanlanA2Rules)}catch(err){$('main').innerHTML='<div class="empty-state">展示数据无法载入：'+String(err.message).replace(/</g,'&lt;')+'</div>';throw err}
 $('demoLabel').textContent='冻结快照 · 主用展示';
 const meta=$('reportMeta');if(meta)meta.innerHTML=`<span style="display:inline-block;width:4px;height:4px;border-radius:50%;background:var(--text);margin-right:6px;box-shadow:0 0 10px #f0f0eb40"></span> 收盘快照 · ${D.end.replaceAll('-','.')}<small style="display:block;color:var(--muted)">${esc(raw.sourceInfo?.label||'来源未提供')}</small>`;
}
/* ---- 全部观察 / 我的收藏 / 观点时间线（架构沿用正式页，黑白样式） ---- */
const kindLabel=r=>!r?'':r.review_kind==='checkpoint_detail'?'节点详评':r.review_kind==='brief'?'简评':r.review_kind==='regular_detail'?'普通详评':'完整复盘';
function retAtDate(s,iso){const i=D.sessions.indexOf(iso);if(i<0)return null;const q=D.history(s)[i];return !s.d0&&V(q?.close)&&V(s.ref)&&s.ref>0&&V(s.recIndex)&&i>=s.recIndex?(q.close/s.ref-1)*100:null}
const OP_TAG_CLASS={'观点增强':'op-strengthened','观点减弱':'op-weakened','维持原判断':'op-maintained','维持原判':'op-maintained','首次复盘':'op-first','尚未复盘':'op-unreviewed','未识别状态':'op-unreviewed'};
const opTagText=(t,invalid)=>`<span class="tag ${invalid||t==='判断失效'?'invalid-pill':OP_TAG_CLASS[t]||'op-maintained'}">${esc(t)}</span>`;
const opTag=s=>opTagText(D.opinion(s),D.invalid(s));
function recordsRows(){const R=window.GuanlanA2Rules,f=state.filters;
 const base=R.filterRecords(raw,f);
 const q=state.query.trim().toLowerCase();
 return !q?base:base.filter(s=>`${s.name} ${s.code} ${s.recDate}`.toLowerCase().includes(q));
}
const favCls=v=>!V(v)?'':tone(v)==='muted'?'':tone(v);
const favStar=(k,on)=>`<button class="star${on?' on':''}" data-star="${esc(k)}" aria-label="${on?'取消收藏':'收藏'}" aria-pressed="${on}">★</button>`;
function recordsTable(rows){
 const sort=state.recordsSort;
 const sortVal={formedOn:s=>(s.formedOn||s.recDate),days:s=>D.daysObserved(s)??-1,
  ret:s=>{const r=window.GuanlanA2Rules.returnOnDate(s);return r===null?-Infinity:r},close:s=>{const c=window.GuanlanA2Rules.closeOnDate(s);return c===null?-Infinity:c}};
 const sorted=[...rows].sort((a,b)=>{const va=sortVal[sort.key](a),vb=sortVal[sort.key](b);return(va<vb?-1:va>vb?1:0)*sort.dir});
 const th=(key,label,sub='')=>{const on=sort.key===key,arrow=on?(sort.dir===1?'↑':'↓'):'⇅';
  return `<th aria-sort="${on?(sort.dir===1?'ascending':'descending'):'none'}"><button class="th-sort" data-sort="${key}">${label}<span class="si">${arrow}</span></button>${sub?`<small class="th-sub">${sub}</small>`:''}</th>`};
 return `<div class="table-wrap"><table class="records-table"><thead><tr>
  <th>股票 / 代码</th>${th('formedOn','推荐日期')}${th('days','观察进度')}${th('ret','价格涨跌','未复权')}${th('close','当日收盘价',`${D.end.slice(5).replace('-','.')} · 元`)}
  <th>复盘观点</th><th class="th-star">收藏</th><th aria-hidden="true"></th>
 </tr></thead><tbody>
 ${sorted.map(s=>{const q=D.quote(s),r=window.GuanlanA2Rules.returnOnDate(s),days=D.daysObserved(s),lr=D.latest(s);
   const k=D.key(s),on=state.favorites.has(k);
   return `<tr data-stock="${esc(k)}" tabindex="0" role="button" aria-label="查看${esc(s.name)}的K线与记录">
  <td><span class="name">${esc(s.name)}</span><small>${esc(s.code)}</small></td>
  <td class="num">${esc((s.formedOn||s.recDate).replaceAll('-','.'))}</td>
  <td>${s.d0?'待首日观察':`第 ${days} 天 / ${daysOf()}`}<span class="prog" aria-hidden="true"><i style="width:${Math.min(100,(days||0)/daysOf()*100)}%"></i></span></td>
  <td class="num ${favCls(r)}">${pct(r)}</td>
  <td class="num">${num(q.close)}</td>
  <td>${opTag(s)}${lr?`<small>${lr.date.slice(5).replace('-','.')} 复盘</small>`:''}</td>
  <td class="td-star">${favStar(k,on)}</td>
  <td class="td-chev" aria-hidden="true">›</td></tr>`}).join('')}
 </tbody></table>${sorted.length?'':'<div class="empty-state">当前条件下没有记录。</div>'}</div>`;
}
function renderRecords(){
 const f=state.filters,rows=recordsRows();
 const scope=f.scope==='invalid'?'仅显示判断失效记录':f.scope==='both'?'显示包含失效记录的完整并集':'显示全部未失效记录';
 $('main').innerHTML=`<div class="page-title between"><div><div class="eyebrow">RECORDS / ALL OBSERVATIONS</div><h1>全部观察。</h1><p>每次入选分别保留；失效记录不删除，只是不进推荐清单。</p></div><div class="report-meta"><span class="dot"></span> 收盘快照 · 上海时间 ${D.end.slice(5).replace('-',' / ')}<small>${esc(D.end)} · 来源：${esc(raw.sourceInfo?.label||'本地归档')}</small></div></div>
 <div class="table-toolbar"><div class="filters">
  <button class="ghost ${['active','both'].includes(f.scope)?'active':''}" data-filter="all">${['active','both'].includes(f.scope)?'✓ ':''}全部（未失效）</button>
  <button class="ghost ${['invalid','both'].includes(f.scope)?'active':''}" data-filter="invalid">${['invalid','both'].includes(f.scope)?'✓ ':''}判断失效</button>
  <button class="ghost ${f.positive?'active':''}" data-filter="positive">高于参考价</button>
  <button class="ghost" data-filter="reset">重置</button>
  <select id="recordOpinion" aria-label="复盘观点筛选">${window.GuanlanA2Rules.OPINION_OPTIONS.map(o=>`<option value="${o.value}" ${f.opinion===o.value?'selected':''}>${o.label}</option>`).join('')}</select>
 </div><input class="input" id="recordSearch" placeholder="搜索名称、代码或入选日期" aria-label="搜索观察记录" value="${esc(state.query)}"></div>
 <p class="scope-summary">${scope}${f.positive?'，且高于参考价':''} · ${rows.length} 条记录</p>
 ${recordsTable(rows)}
 <p class="scope-note">先点“判断失效”只看失效记录；先点“全部（未失效）”再点“判断失效”，显示含失效的完整并集。样例中的无参考价记录显示“—”，不是 0%。价格涨跌按未复权报价计算；完整复盘同时显示正式复权涨跌，分红送转可能造成差异。点击行查看该次推荐的 40 日 K 线。观察目标 20% 为原口径展示，不是预测。</p>`;
}
function renderFavorites(){
 const rows=[...state.favorites].map(k=>raw.stocks.find(s=>D.key(s)===k)).filter(Boolean)
  .sort((a,b)=>b.recDate.localeCompare(a.recDate));
 $('main').innerHTML=`<div class="page-title between"><div><div class="eyebrow">FAVORITES / MY LIST</div><h1>我的收藏。</h1><p>收藏只保存在本浏览器；在全部观察里点行尾星标即可添加或移除。</p></div><div class="report-meta"><span class="dot"></span> 收盘快照 · 上海时间 ${D.end.slice(5).replace('-',' / ')}<small>${esc(D.end)} · 来源：${esc(raw.sourceInfo?.label||'本地归档')}</small></div></div>
 ${rows.length?recordsTable(rows):`<div class="panel empty-state">还没有收藏的记录。<br>在「全部观察」里点行尾的 ★ 即可添加；收藏只保存在本浏览器。</div>`}
 <p class="scope-note">收藏不是新的推荐名单，只是本浏览器里的快速入口；数据仍来自同一份冻结快照。</p>`;
}
function renderJournal(){
 if(!state.journalDate)state.journalDate=raw.review_dates?.[0]||D.end;
 const ds=state.journalDate;
 const jUpdates=window.GuanlanA2Rules.directionUpdates({...raw,analysis_date:ds});
 const entries=state.journalMode==='directions'?jUpdates.map(x=>({s:x.s,r:x.r,x})):
  raw.stocks.flatMap(s=>s.reviews.filter(r=>r.date===ds&&(state.journalMode==='all'||r.viewChanged)).map(r=>({s,r,x:null})));
 const toUp=jUpdates.filter(x=>x.to==='up').length,toDown=jUpdates.filter(x=>x.to==='down').length;
 const sameYear=iso=>iso.slice(0,4)===ds.slice(0,4);
 $('main').innerHTML=`<div class="page-title between"><div><div class="eyebrow">JOURNAL / CHANGING MINDS</div><h1>观点时间线。</h1><p>先看方向发生了什么变化，再看变化的原因。</p></div><div class="report-meta"><span class="dot"></span> 收盘快照 · 上海时间 ${D.end.slice(5).replace('-',' / ')}<small>${esc(raw.sourceInfo?.label||'本地归档')}</small></div></div>
 <div class="journal-layout"><aside class="panel journal-side">
  <h2>${ds.slice(5,7)} <small style="font-size:12px;color:var(--muted)">/ ${ds.slice(0,4)}</small></h2>
  <p class="journal-sub">复盘归属日期，不是报告实际生成时点</p>
  <dl><div><dt>本日方向更新</dt><dd>${jUpdates.length}</dd></div><div><dt>转为上涨</dt><dd>${toUp}</dd></div><div><dt>转为下跌</dt><dd>${toDown}</dd></div></dl>
  <select id="journalDate" aria-label="选择复盘日期">${(raw.review_dates||[]).map(d=>`<option value="${d}" ${d===ds?'selected':''}>${d}</option>`).join('')}</select>
  <div class="mini-tabs" style="margin-top:12px" aria-label="时间线模式">
   <button data-journal-mode="directions" class="${state.journalMode==='directions'?'active':''}">方向更新</button>
   <button data-journal-mode="changes" class="${state.journalMode==='changes'?'active':''}">全部观点调整</button>
   <button data-journal-mode="all" class="${state.journalMode==='all'?'active':''}">当日全部复盘</button>
  </div>
 </aside><div class="journal-feed">
 ${entries.length?entries.map(({s,r,x})=>{const ret=retAtDate(s,r.date);return `<article class="journal-entry"><div class="panel"><div class="entry-top"><h3>${esc(s.name)}<small>${s.code} · 复盘 ${r.date} · 推荐 ${s.formedOn||s.recDate} · 开始观察 ${s.recDate}</small></h3>${opTagText(r.viewLabel||'观点标签暂缺',r.viewChange==='invalidated'||r.assessmentCode==='contradicted')}</div>
  ${x?`<div class="transition"><span class="tag ${x.from==='up'?'up':x.from==='down'?'down':''}">${x.fromLabel}</span><span class="arrow">→</span><span class="tag ${x.to==='up'?'up':x.to==='down'?'down':''}">${x.toLabel}</span><small class="muted">未来 1—3 日方向</small></div>
  <div class="entry-body"><p>${esc(r.outlookReason||r.viewReason||'原文未提供。')}</p>
  <div class="transition-detail"><span>${x.previous.date}：${esc(x.previous.base||'短期展望原文暂缺')}</span><span>${r.date}：${esc(r.base||'短期展望原文暂缺')}</span></div>
  <p class="journal-reason" style="font-size:10px;color:var(--muted);margin-top:8px">相比上次：${esc(r.viewReason||'未保存比较原因')}</p></div>`
   :`<div class="entry-body"><p>${esc(r.viewReason||r.summary_copy||'原文未提供。')}</p></div>`}
  <div class="entry-foot"><span>第 ${r.day} 天 · ${kindLabel(r)} · <b class="${tone(ret)}">${pct(ret)}</b> 价格涨跌（未复权）</span>
  <button class="text-button" data-stock="${esc(D.key(s))}" data-date="${esc(r.date)}" data-tab="review">回到这一天 →</button></div></div></article>`}).join('')
  :`<div class="panel empty-state">这一天没有${state.journalMode==='directions'?'方向更新':state.journalMode==='changes'?'观点调整':'复盘记录'}。不把“同方向内信心增强或减弱”当作方向变化，也不为首次复盘补写上一观点。</div>`}
 </div></div>`;
}
/* 事件：全部文档级委托，页面骨架重建后依然有效 */
document.addEventListener('click',e=>{
 const dt=e.target.closest('[data-detail-tab]');
 if(dt&&state.modal?.type==='stock'){state.modal.tab=dt.dataset.detailTab;drawModalChart();return}
 const flt=e.target.closest('[data-filter]');
 if(flt){state.filters=window.GuanlanA2Rules.filterAction(state.filters,flt.dataset.filter,flt.dataset.value);renderRecords();return}
 const jm=e.target.closest('[data-journal-mode]');
 if(jm){state.journalMode=jm.dataset.journalMode;renderJournal();return}
 const starB=e.target.closest('[data-star]');
 if(starB){const k=starB.dataset.star;
  state.favorites.has(k)?state.favorites.delete(k):state.favorites.add(k);
  try{localStorage.setItem('guanlan.a2.favorites',JSON.stringify([...state.favorites]))}catch{}
  window.A2Notify?.(state.favorites.has(k)?'已收藏该次入选记录（仅保存在本浏览器）':'已取消收藏');
  if(state.page==='favorites')renderFavorites();else renderRecords();return}
 const thB=e.target.closest('.th-sort');
 if(thB){const key=thB.dataset.sort;
  if(state.recordsSort.key===key)state.recordsSort.dir*=-1;else state.recordsSort={key,dir:-1};
  if(state.page==='favorites')renderFavorites();else renderRecords();return}
 const fs=e.target.closest('[data-focus-step]');
 if(fs&&!fs.disabled)return setFocus(state.focus+Number(fs.dataset.focusStep));
 const b=e.target.closest('[data-index],[data-stock],[data-update],[data-review-date],[data-chart-mode],[data-modal-mode],[data-metric],[data-period],[data-modal-metric],[data-rail]');
 if(!b)return;
 if(b.dataset.index!==undefined)return openIndex(Number(b.dataset.index),b);
 if(b.dataset.stock)return openStock(b.dataset.stock,b,b.dataset.date,b.dataset.tab||'chart');
 if(b.dataset.update!==undefined){const u=D.updates[Number(b.dataset.update)];return openReview(u.s,u.r,u.previous,b)}
 if(b.dataset.reviewDate){const s=current(),r=D.ordered(s).find(r=>r.date===b.dataset.reviewDate);return openReview(s,r,null,b)}
 if(b.dataset.chartMode){if(state.mode===b.dataset.chartMode)return;state.mode=b.dataset.chartMode;document.querySelectorAll('[data-chart-mode]').forEach(x=>{x.classList.toggle('active',x.dataset.chartMode===state.mode);x.setAttribute('aria-pressed',String(x.dataset.chartMode===state.mode))});return renderHeroChart(false)}
 if(b.dataset.period){state.period=Number(b.dataset.period);return drawWidgets(true)}
 if(b.dataset.metric){state.metric=b.dataset.metric;drawWidgets(true);document.querySelectorAll('.chart-context [data-metric]').forEach(x=>x.classList.toggle('active',x.dataset.metric===state.metric));return renderHeroChart(false)}
 if(b.dataset.modalMode){state.modalMode=b.dataset.modalMode;return drawModalChart()}
 if(b.dataset.modalMetric){state.modalMetric=b.dataset.modalMetric;return drawModalChart()}
 if(b.dataset.rail){const rail=$(b.dataset.rail);rail?.scrollBy({left:Number(b.dataset.step)*(rail.clientWidth+14),behavior:motion()?'smooth':'auto'})}
});
document.addEventListener('change',e=>{
 if(e.target.id==='detailDate'&&state.modal?.type==='stock'){state.modal.date=e.target.value;drawModalChart();return}
 if(e.target.id==='stockSelect')setFocus(Number(e.target.value));
 if(e.target.id==='episodeSelect')setFocus(state.focus,Number(e.target.value));
 if(e.target.id==='recordOpinion'){state.filters=window.GuanlanA2Rules.filterAction(state.filters,'opinion',e.target.value);renderRecords()}
 if(e.target.id==='journalDate'){state.journalDate=e.target.value;renderJournal()}
});
document.addEventListener('input',e=>{
 if(e.target.id==='recordSearch'){const pos=e.target.selectionStart;state.query=e.target.value;renderRecords();const el=$('recordSearch');el.focus();try{el.setSelectionRange(pos,pos)}catch{}}
});
document.addEventListener('keydown',e=>{
 if(e.target.matches('.review-node')&&['Enter',' '].includes(e.key)){e.preventDefault();e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}))}
 if(e.target.matches('tr[data-stock]')&&['Enter',' '].includes(e.key)){e.preventDefault();e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}))}
});
$('motionToggle').onclick=()=>{state.motion=!state.motion;if(!motion())document.getAnimations().forEach(a=>a.finish());motionButton()};reduced.addEventListener('change',()=>{if(reduced.matches)document.getAnimations().forEach(a=>a.finish());motionButton()});$('notesButton').onclick=e=>{ensureData();openNotes(e.currentTarget)};$('closeDialog').onclick=closeWindow;dialog.addEventListener('cancel',e=>{e.preventDefault();closeWindow()});let outsideDown=false;dialog.addEventListener('pointerdown',e=>outsideDown=e.target===dialog);dialog.addEventListener('click',e=>{if(e.target===dialog&&outsideDown)closeWindow()});
let resize;window.addEventListener('resize',()=>{clearTimeout(resize);resize=setTimeout(()=>{if(!D)return;if(current()&&$('heroPlot'))renderHeroChart(false);if(state.modal&&(state.modal.type==='index'||state.modal.tab==='chart'))drawModalChart();$('stockRail')?._sync?.();$('updatesRail')?._sync?.()},140)},{passive:true});
document.addEventListener('scroll',()=>{$('chartTooltip').hidden=true},{passive:true});
function motionButton(){const b=$('motionToggle');b.textContent=reduced.matches?'系统已减少动效':`动效 ${motion()?'开启':'关闭'}`;b.setAttribute('aria-pressed',String(motion()));b.disabled=reduced.matches}
/* 壳层 render() 钩子：总览由壳层给骨架，其余页面在此渲染（架构沿用正式页，黑白样式） */
window.A2Hook={openStock,onRender(page,animate){ensureData();state.page=page;
 if(page==='overview')return renderAll(false);
 if(page==='records')return renderRecords();
 if(page==='journal')return renderJournal();
 if(page==='favorites')return renderFavorites();
}};
if($('marketStrip')){ensureData();motionButton();renderAll(true)}
window.PrismA2Debug=Object.freeze({state:()=>({...state,modal:state.modal?.type||null}),data:()=>({focusKeys:D.deep.map(g=>g.records.map(D.key)),issues:[...D.issues],sessions:D.sessions.length,stocks:raw.stocks.length}),viewModel:D});
})();
