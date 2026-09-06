/* 观澜 · Standalone presentation demo. All content stays local. */
(function(){
'use strict';
const DATA=JSON.parse(document.getElementById('snapshot').textContent);
const C=window.GuanlanCore, LAST=DATA.dates.length-1, stocks=DATA.stocks;
const $=id=>document.getElementById(id);
const escape=t=>String(t??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const pct=v=>C.valid(v)?`${v>0?'+':''}${Math.abs(v)<0.00001?'0.00':v.toFixed(2)}%`:'—';
const money=v=>C.valid(v)?v.toFixed(2):'—';
const signedClass=v=>!C.valid(v)||Math.abs(v)<1e-8?'secondary':v>0?'positive':'negative';
const byId=id=>stocks.find(s=>C.key(s)===id);
const byName=name=>stocks.find(s=>s.name===name);
const readStore=k=>{try{return localStorage.getItem(k)}catch{return null}};
const writeStore=(k,v)=>{try{localStorage.setItem(k,v);return true}catch{return false}};
let favorites=[];try{favorites=JSON.parse(readStore('guanlan.favorites')||'[]');if(!Array.isArray(favorites))favorites=[]}catch{}
// Showcase order is presentation only, never a recommendation ranking.
// Production renderers set presentation.demoShowcase=false and retain source order.
const presentation=DATA.presentation||{};
function chooseExamples(names, suppliedKeys=[]){
 const preferred=suppliedKeys.length?suppliedKeys.map(byId):presentation.demoShowcase===false?[]:names.map(byName);
 return [...new Map([...preferred.filter(Boolean),...stocks].map(s=>[C.key(s),s])).values()].slice(0,4);
}
const heroStocks=chooseExamples(['银龙股份','中国广核','德尔股份','杭氧股份'],presentation.heroKeys||[]);
const displayDate=DATA.analysis_date.replaceAll('-','.');
const displayWeekday=['SUN','MON','TUE','WED','THU','FRI','SAT'][new Date(DATA.analysis_date+'T12:00:00Z').getUTCDay()]||'';
const state={page:'overview',filter:'all',query:'',sort:'date',direction:-1,cardMode:'focus',hero:0,
  current:heroStocks.length?C.key(heroStocks[0]):'',end:LAST,chartMode:'line',reviewTab:'latest',journalDate:DATA.analysis_date,
  onlyChanges:true,mapCurrent:heroStocks.length?C.key(heroStocks[0]):'',favorites:new Set(favorites),searchIndex:0,searchList:[],playing:false};
let playback=null,toastTimer=null,resizeTimer=null,plotId=0;
const paths={
 grid:'<rect x="3" y="3" width="6" height="6" rx="1.3"/><rect x="15" y="3" width="6" height="6" rx="1.3"/><rect x="3" y="15" width="6" height="6" rx="1.3"/><rect x="15" y="15" width="6" height="6" rx="1.3"/>',
 layers:'<path d="m12 3 10 5-10 5L2 8l10-5Zm-10 9 10 5 10-5M2 17l10 5 10-5"/>',
 orbit:'<circle cx="12" cy="12" r="3"/><ellipse cx="12" cy="12" rx="10" ry="5" transform="rotate(-35 12 12)"/><path d="M6 4c2-2 7 0 10 5s4 10 2 11"/><circle cx="5" cy="16" r="1.5" fill="currentColor"/>',
 history:'<path d="M3 4v5h5M3.8 8A9 9 0 1 1 3 14M12 7v5l3 2"/>',
 star:'<path d="m12 3 2.8 5.7 6.3.9-4.6 4.4 1.1 6.3L12 17.4l-5.6 2.9 1.1-6.3L3 9.6l6.2-.9L12 3Z"/>',
 search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
 'arrow-right':'<path d="M4 12h16m-6-6 6 6-6 6"/>',
 'arrow-left':'<path d="M20 12H4m6-6-6 6 6 6"/>',
 'arrow-up-right':'<path d="M6 18 18 6M6 6h12v12"/>',
 'chevron-left':'<path d="m14 6-6 6 6 6"/>',
 'chevron-right':'<path d="m10 6 6 6-6 6"/>',
 info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
 expand:'<path d="M9 3H3v6m12-6h6v6M3 15v6h6m12-6v6h-6"/>',
 sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
 moon:'<path d="M21 13A9 9 0 0 1 11 3 9 9 0 1 0 21 13Z"/>',
 compass:'<circle cx="12" cy="12" r="9"/><path d="m16 8-3 5-5 3 3-5 5-3Z"/>',
 calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18m-13 5h2m4 0h2"/>',
 trend:'<path d="m3 17 6-6 4 4 8-10m-6 0h6v6"/>',
 pulse:'<path d="M2 12h4l3-7 5 14 3-7h5"/>',
 flag:'<path d="M5 21V3m0 1c6-4 8 4 15 0v10c-7 4-9-4-15 0"/>',
 play:'<path d="m8 4 12 8-12 8V4Z" fill="currentColor" stroke="none"/>',
 pause:'<path d="M8 5v14M16 5v14" stroke-width="3"/>',
 download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
 close:'<path d="m6 6 12 12M6 18 18 6"/>',
 check:'<path d="m5 12 4 4L19 6"/>',
 minus:'<path d="M5 12h14"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
 sparkles:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',
 book:'<path d="M12 5v16M3 4c3-1 6-1 9 1 3-2 6-2 9-1v15c-3-1-6-1-9 1-3-2-6-2-9-1V4Z"/>',
 target:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
 chart:'<path d="M4 3v17h17M8 15v-4m5 4V6m5 9V9"/>',
 eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>'
};
const icon=name=>`<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name]||paths.pulse}</svg>`;
function hydrate(root=document){root.querySelectorAll('[data-icon]').forEach(el=>{el.innerHTML=icon(el.dataset.icon)})}
function tone(r){return C.reviewTone(r)}
function viewPill(r,fallback='尚无复盘'){return `<span class="pill ${tone(r)}">${r&&r.viewChanged?icon(r.viewLabel==='观点增强'?'trend':r.viewLabel==='判断失效'?'close':'minus'):''}${escape(r?.viewLabel||fallback)}</span>`}
function baseLabel(r){return r?r.base.replace(/^未来1—3个交易日更可能/,'').replace(/^先等待事件或复牌后的实际交易反应，方向暂时无法判断$/,'等待实际交易反应'):'尚无复盘观点'}
// 复盘三路：节点详评 / 普通详评 / 简评；未知类型按源数据原样标注为完整复盘。
function kindLabel(r){return !r?'':r.review_kind==='checkpoint_detail'?'节点详评':r.review_kind==='brief'?'简评':r.review_kind==='regular_detail'?'普通详评':'完整复盘'}
function star(s){const saved=state.favorites.has(C.key(s));return `<button class="icon-btn star-button ${saved?'saved':''}" data-star="${C.key(s)}" aria-label="${saved?'取消收藏':'收藏'}${escape(s.name)}" aria-pressed="${saved}">${icon('star')}</button>`}
function progress(s,end=LAST){return s.d0?'待首日观察':`第 ${C.daysAt(s,end)} 天 <span class="muted">/ 20</span>`}
function simplePath(values,x,y){let d='',open=false;values.forEach((v,i)=>{if(!C.valid(v)){open=false;return}d+=`${open?'L':'M'}${x(i).toFixed(2)},${y(v).toFixed(2)} `;open=true});return d}
function spark(s){
 const vals=s.candles.map(c=>c?.[3]??null).slice(s.d0?-10:s.recIndex),good=vals.filter(C.valid);
 if(!good.length)return `<svg class="spark" viewBox="0 0 90 36" aria-hidden="true"></svg>`;
 let lo=Math.min(...good),hi=Math.max(...good);if(hi===lo){lo-=.01;hi+=.01}
 const x=i=>3+(i/Math.max(vals.length-1,1))*84,y=v=>31-(v-lo)/(hi-lo)*25;
 const d=simplePath(vals,x,y),m=C.metrics(s,LAST),color=m.ret===null?'var(--muted)':m.ret>=0?'var(--up)':'var(--down)';
 return `<svg class="spark" viewBox="0 0 90 36" aria-hidden="true"><path d="${d}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" ${s.d0?'stroke-dasharray="3 3"':''}/><circle cx="${x(vals.length-1)}" cy="${y(good.at(-1))}" r="2" fill="${color}"/></svg>`;
}
function intro(kicker,title,subtitle,extra='date'){
 return `<section class="intro"><div><span class="eyebrow">${kicker}</span><h1>${title}</h1><p>${subtitle}</p></div>${extra==='date'?`<div class="date-box">${icon('calendar')}<div><strong>${displayDate} <span class="muted">${displayWeekday}</span></strong><small>收盘快照 · 上海时间</small></div></div>`:extra}</section>`;
}
function plot(s,end=LAST,mode='line',hero=false){return `<svg class="chart main-plot" data-stock="${C.key(s)}" data-end="${end}" data-mode="${mode}" data-hero="${hero}" role="img" tabindex="0" aria-label="${escape(s.name)}截至${C.dateAt(end,DATA)}的${mode==='candle'?'K线':mode==='relative'?'相对表现':'收盘走势'}图"></svg>`}
function card(s){const r=C.reviewAt(s,LAST,DATA),m=C.metrics(s,LAST);return `<article class="observation-card" data-open="${C.key(s)}" tabindex="0" role="button" aria-label="查看${escape(s.name)} ${s.recDate}观察"><div class="card-top"><div><h3 class="card-name">${escape(s.name)}</h3><div class="card-code">${s.code} · ${s.recDate.slice(5).replace('-','.')}</div></div>${star(s)}</div><div class="card-price-row"><strong class="num ${signedClass(m.ret)}">${pct(m.ret)}</strong>${spark(s)}</div><div class="card-caption">${s.d0?'推荐日尚未到达':m.ret===null?'暂无可靠参考价':'收盘较原参考价'}</div><div class="card-bottom">${viewPill(r,s.d0?'待首日观察':s.stage)}<span>${progress(s)}</span></div></article>`}
function currentChanges(date=DATA.analysis_date){return stocks.flatMap(s=>s.reviews.filter(r=>r.date===date&&r.viewChanged).map(r=>({s,r})))}
function overview(){
 const valid=stocks.filter(s=>C.metrics(s,LAST).ret!==null),up=valid.filter(s=>C.metrics(s,LAST).ret>0).length,attention=stocks.filter(s=>s.attention).length,changes=currentChanges(),s=heroStocks[state.hero],m=C.metrics(s,LAST),r=C.reviewAt(s,LAST,DATA);
 const preferredChanges=presentation.demoShowcase===false?[]:['银龙股份','德尔股份','汉得信息','中国广核'].map(n=>changes.find(x=>x.s.name===n)).filter(Boolean);
 const featured=[...new Map([...preferredChanges,...changes].map(item=>[C.key(item.s),item])).values()].slice(0,4);
 const cards=state.cardMode==='focus'?chooseExamples(['中国广核','德尔股份','杭氧股份','鸿富瀚'],presentation.cardKeys||[]):stocks.slice(0,4);
 return `<div class="page-enter">${intro('AFTER THE CLOSE / BEFORE THE NEXT MOVE','收盘之后，<span class="intro-accent">看清变化。</span>','不止看涨跌，也看当初的判断，是否仍然成立。')}
 <div class="stats-grid">
 <button class="stat-card" data-nav="records"><div class="stat-title">观察记录 ${icon('layers')}</div><div class="stat-value"><b>${stocks.length}</b><small>条独立记录</small></div><div class="stat-mini">${new Set(stocks.map(s=>s.code)).size} 只股票 · 同股分次记录</div><div class="stat-graphic stat-bars" aria-hidden="true">${[9,16,12,22,18,26,20,30].map((h,i)=>`<i style="--h:${h}px;--o:${.16+i*.07}"></i>`).join('')}</div></button>
 <button class="stat-card" data-action="attention"><div class="stat-title">重点关注 ${icon('eye')}</div><div class="stat-value"><b>${attention.toString().padStart(2,'0')}</b><small>条</small></div><div class="stat-mini">沿用原报告的重点标记</div><div class="stat-graphic" aria-hidden="true" style="right:11px;bottom:15px;opacity:.45"><svg viewBox="0 0 68 28" fill="none"><path d="M1 17h14l7-11 8 18 9-17 5 10h20" stroke="var(--accent)" stroke-width="1.4"/></svg></div></button>
 <button class="stat-card" data-nav="journal"><div class="stat-title">本期观点调整 ${icon('history')}</div><div class="stat-value"><b>${changes.length}</b><small>条</small></div><div class="stat-mini">${changes.filter(x=>x.r.viewLabel==='观点增强').length} 条增强 · ${changes.filter(x=>x.r.viewLabel==='判断失效').length} 条失效</div></button>
 <button class="stat-card" data-action="positive"><div class="stat-title">高于参考价 ${icon('trend')}</div><div class="stat-value"><b>${up}</b><small>/ ${valid.length} 条可计算记录</small></div><div class="stat-track" aria-hidden="true"><i style="width:${up/valid.length*100}%"></i><i style="width:${(valid.length-up)/valid.length*100}%"></i></div></button>
 </div>
 <div class="overview-grid">
 <section class="panel hero-panel"><div class="panel-head"><div class="panel-heading">${icon('pulse')}走势聚焦 <small>OBSERVATION IN FOCUS</small></div><button class="small-link" data-open="${C.key(s)}">进入完整复盘 ${icon('arrow-up-right')}</button></div><div class="hero-top"><div class="stock-title"><span class="stock-token">${escape(s.name[0])}</span><div><h2>${escape(s.name)}</h2><small>${s.code} <span style="margin-left:7px">${escape(s.industryName)}</span></small></div></div><div class="hero-metric"><strong class="num ${signedClass(m.ret)}">${pct(m.ret)}</strong><small>推荐后第 ${s.days} 天 · 收盘较参考价</small></div></div><div class="hero-summary">${viewPill(r)}<span>${escape(r?.viewReason||s.reasonFull)}</span></div><div class="hero-chart">${plot(s,LAST,'line',true)}</div><div class="hero-foot"><div class="mini-legend"><span><i class="legend-line"></i>收盘价</span><span><i class="legend-line dashed"></i>推荐参考价</span><span><i class="legend-line target"></i>20%观察目标</span></div><div class="hero-cycle"><span>${String(state.hero+1).padStart(2,'0')} / ${String(heroStocks.length).padStart(2,'0')}</span><button class="icon-btn" data-hero-step="-1" aria-label="上一条聚焦记录">${icon('chevron-left')}</button><button class="icon-btn" data-hero-step="1" aria-label="下一条聚焦记录">${icon('chevron-right')}</button></div></div></section>
 <section class="panel changes-panel"><div class="panel-head"><h2 class="panel-heading">观点变化摘录 <span class="change-total">${changes.length}</span></h2><button class="small-link" data-nav="journal">全部 ${icon('arrow-up-right')}</button></div><div class="change-list">${featured.map(({s,r})=>`<button class="change-item" data-open="${C.key(s)}"><div class="change-title"><span class="change-name">${escape(s.name)}</span>${viewPill(r)}</div><div class="change-meta"><span>第 ${r.day} 天</span><span class="${signedClass(C.metrics(s,LAST).ret)}">${pct(C.metrics(s,LAST).ret)}</span></div><p>${escape(r.viewReason)}</p></button>`).join('')}</div></section>
 </div>
 <div class="section-heading"><h2>你的观察清单 <small>ON YOUR RADAR</small></h2><div class="section-actions"><div class="segmented" aria-label="切换卡片"><button class="${state.cardMode==='focus'?'active':''}" data-card-mode="focus">不同状态示例</button><button class="${state.cardMode==='recent'?'active':''}" data-card-mode="recent">近期推荐</button></div><button class="small-link" data-nav="records">全部 ${stocks.length} 条 ${icon('arrow-right')}</button></div></div>
 <div class="observation-cards">${cards.map(card).join('')}</div>
 <div class="overview-note">${icon('orbit')}<span><b>换个角度看全局。</b> 在观察星图中，比较每条记录的观察进度与价格表现。</span><button data-nav="map">探索观察星图 ↗</button></div>
 </div>`;
}
function filteredStocks(){
 let list=stocks.filter(s=>state.page!=='favorites'||state.favorites.has(C.key(s)));
 if(state.filter==='attention')list=list.filter(s=>s.attention);
 if(state.filter==='positive')list=list.filter(s=>C.metrics(s,LAST).ret>0);
 if(state.filter==='changes')list=list.filter(s=>s.reviews.some(r=>r.date===DATA.analysis_date&&r.viewChanged));
 if(state.filter==='pending')list=list.filter(s=>s.d0||s.ref===null);
 const q=state.query.trim().toLowerCase();if(q)list=list.filter(s=>`${s.name} ${s.code} ${s.industryName} ${s.recDate}`.toLowerCase().includes(q));
 return list.sort((a,b)=>{if(state.sort==='return'){const av=C.metrics(a,LAST).ret,bv=C.metrics(b,LAST).ret;if(av===null)return 1;if(bv===null)return -1;return (av-bv)*state.direction}
 if(state.sort==='days')return(a.days-b.days)*state.direction;return a.recDate.localeCompare(b.recDate)*state.direction});
}
function tableRows(){return filteredStocks().map(s=>{const m=C.metrics(s,LAST),r=C.reviewAt(s,LAST,DATA);return `<tr data-open="${C.key(s)}" tabindex="0" role="button" aria-label="打开${escape(s.name)} ${s.recDate}的复盘"><td><div class="table-stock"><span class="stock-token sm">${escape(s.name[0])}</span><div><strong>${escape(s.name)}</strong><small>${s.code}</small></div></div></td><td><span class="mono secondary">${s.recDate.replaceAll('-','.')}</span></td><td>${progress(s)}<div class="table-progress"><i style="width:${Math.min(s.days/20,1)*100}%"></i></div></td><td><b class="num ${signedClass(m.ret)}">${pct(m.ret)}</b></td><td><span class="num secondary">${pct(m.max)}</span></td><td>${viewPill(r,s.d0?'待首日观察':s.stage)}<div class="card-caption">${escape(s.industryName)}</div></td><td><div style="display:flex;align-items:center;gap:10px">${star(s)}${icon('chevron-right')}</div></td></tr>`}).join('')}
function records(){
 const fav=state.page==='favorites',labels=[['all','全部'],['attention','重点关注'],['changes','观点调整'],['positive','高于参考价'],['pending','待确认参考价']];
 return `<div class="page-enter">${intro(fav?'SAVED OBSERVATIONS':'EVERY THESIS / EVERY RECORD',fav?'留给自己，多看一眼。':'每一条判断，都留下记录。',fav?'收藏保存在当前浏览器，只是阅读清单，不是持仓。':'同一股票的不同推荐分别保留；价格表现不等于判断仍然成立。',`<button class="quiet-btn" data-action="export">${icon('download')}导出快照</button>`)}
 <div class="toolbar"><div class="filter-tabs" aria-label="筛选观察记录">${labels.map(([id,label])=>`<button class="filter-tab ${state.filter===id?'active':''}" data-filter="${id}" aria-pressed="${state.filter===id}">${label}</button>`).join('')}</div><div class="toolbar-right"><label class="inline-search">${icon('search')}<input id="recordSearch" placeholder="名称、代码、行业" aria-label="筛选股票" value="${escape(state.query)}"></label></div></div>
 <section class="panel"><div class="table-wrap"><table class="records-table"><thead><tr><th>股票 / 代码</th><th><button data-sort="date">推荐日期 ${state.sort==='date'?(state.direction<0?'↓':'↑'):'↕'}</button></th><th><button data-sort="days">观察进度 ${state.sort==='days'?(state.direction<0?'↓':'↑'):'↕'}</button></th><th><button data-sort="return">较参考价涨跌 ${state.sort==='return'?(state.direction<0?'↓':'↑'):'↕'}</button></th><th>最高收盘涨跌</th><th>最近复盘观点 / 行业</th><th></th></tr></thead><tbody id="tableRows">${tableRows()}</tbody></table></div><div class="empty" id="tableEmpty" ${filteredStocks().length?'hidden':''}>${icon(fav?'star':'search')}<h3>${fav&&!state.favorites.size?'还没有收藏记录':'没有匹配的观察记录'}</h3><p>${fav&&!state.favorites.size?'点股票旁的星标，就能在这里找到它。':'换一个名称、代码或筛选条件再看看。'}</p><button class="quiet-btn" data-nav="records">查看全部观察 ${icon('arrow-right')}</button></div><div class="table-bottom"><span id="tableCount">${filteredStocks().length} 条记录</span><span>数据口径见说明 · 无参考价不计算涨跌</span></div></section>
 </div>`;
}
function mapSelection(s){if(!s)return '<div class="empty"><h3>暂无可展示记录</h3></div>';const m=C.metrics(s,LAST),r=C.reviewAt(s,LAST,DATA),q=C.quoteAt(s,LAST);return `<span class="eyebrow">SELECTED OBSERVATION</span><div class="stock-title"><span class="stock-token">${escape(s.name[0])}</span><div><h2>${escape(s.name)}</h2><small>${s.code}</small></div></div><div class="big-return ${signedClass(m.ret)}">${pct(m.ret)}</div><span class="source-hint">收盘较原参考价</span><dl><div><dt>观察进度</dt><dd>${progress(s)}</dd></div><div><dt>推荐日期</dt><dd class="mono">${s.recDate}</dd></div><div><dt>本期成交额</dt><dd class="mono">${money(q?.c[4])} 亿</dd></div></dl>${viewPill(r,s.stage)}<p>${escape(r?.viewReason||s.reasonFull.slice(0,90)+'…')}</p><button class="primary-btn" data-open="${C.key(s)}">阅读完整复盘 ${icon('arrow-right')}</button>`}
function mapPage(){return `<div class="page-enter">${intro('THE OBSERVATION ATLAS','每一次推荐，都有自己的坐标。','横向看观察天数，纵向看较参考价涨跌。一个光点，就是一次独立观察。')}
 <div class="map-layout"><section class="panel map-panel"><div class="panel-head"><h2 class="panel-heading">${icon('orbit')}观察星图 <small>PERFORMANCE × TIME</small></h2><span class="source-hint">${stocks.filter(s=>C.metrics(s,LAST).ret!==null).length} 条有参考价的记录</span></div><div class="map-wrap"><svg id="atlas" class="chart" role="img" aria-label="股票观察天数和较参考价涨跌散点图"></svg></div><div class="graph-key"><span class="chip-dot"></span>高于参考价 <span class="chip-dot down"></span>低于参考价 <span style="margin-left:8px">圆点大小＝本期成交额（压缩比例）</span></div><p class="map-note">悬停查看记录，点击进入复盘。无参考价的记录不绘制；这是表现分布，不是新的推荐排名。</p></section><aside class="panel map-selection" id="mapSelection">${mapSelection(byId(state.mapCurrent))}</aside></div></div>`}
function journal(){
 const entries=stocks.flatMap(s=>s.reviews.filter(r=>r.date===state.journalDate&&(!state.onlyChanges||r.viewChanged)).map(r=>({s,r})));
 const changes=currentChanges(state.journalDate),enhanced=changes.filter(x=>x.r.viewLabel==='观点增强').length,weak=changes.filter(x=>x.r.viewLabel==='观点减弱').length,invalid=changes.filter(x=>x.r.viewLabel==='判断失效').length;
 return `<div class="page-enter">${intro('A JOURNAL OF CHANGING MINDS','好的复盘，也记录改变。','不只保留看对的时刻。理由增强、预期减弱、判断失效，都值得回看。',`<div class="segmented"><button data-journal-mode="changes" class="${state.onlyChanges?'active':''}">只看观点调整</button><button data-journal-mode="all" class="${!state.onlyChanges?'active':''}">当日全部复盘</button></div>`)}
 <div class="journal-layout"><aside class="journal-side"><h2>${state.journalDate.slice(-2)}<span class="muted" style="font-size:26px"> / ${state.journalDate.slice(5,7)}</span></h2><p>${state.journalDate.slice(0,4)} · 复盘归属日期<br>不是报告实际生成时点</p><dl><div><dt>观点增强</dt><dd class="accent">${enhanced.toString().padStart(2,'0')}</dd></div><div><dt>观点减弱</dt><dd class="amber">${weak.toString().padStart(2,'0')}</dd></div><div><dt>判断失效</dt><dd class="positive">${invalid.toString().padStart(2,'0')}</dd></div></dl><label class="sr-only" for="journalDate">复盘日期</label><select class="select-input" id="journalDate">${DATA.review_dates.map(d=>`<option value="${d}" ${d===state.journalDate?'selected':''}>${d.replaceAll('-',' / ')}</option>`).join('')}</select></aside><div class="journal-feed">${entries.length?entries.map(({s,r})=>{const index=DATA.dates.indexOf(r.date.slice(5)),m=C.metrics(s,index);return `<article class="journal-entry ${tone(r)}"><div class="panel"><div class="entry-top"><div style="display:flex;align-items:center;gap:10px"><span class="stock-token sm">${escape(s.name[0])}</span><h3>${escape(s.name)}</h3></div>${viewPill(r)}</div><p>${escape(r.viewReason||r.summary_copy)}</p><div class="entry-foot"><span>第 ${r.day} 天 <span style="margin:0 8px">·</span>${kindLabel(r)} <span style="margin:0 8px">·</span><span class="${signedClass(m.ret)}">${pct(m.ret)}</span> 较参考价</span><button class="small-link" data-open="${C.key(s)}" data-open-end="${index}">回到这一天 ${icon('arrow-up-right')}</button></div></div></article>`}).join(''):`<div class="empty">${icon('history')}<h3>这一天没有${state.onlyChanges?'观点调整':'复盘记录'}</h3><p>未记录的内容不会补写。</p></div>`}</div></div></div>`;
}
function detail(){
 const s=byId(state.current),end=state.end,m=C.metrics(s,end),q=C.quoteAt(s,end),r=C.reviewAt(s,end,DATA),days=C.daysAt(s,end),isLatest=end===LAST;
 const fields=[['收盘价',q?'¥ '+money(q.c[3]):'—','',q?`${DATA.dates[q.i]} · 当日 ${pct(C.dayChange(s,q.i))}`:'没有有效报价'],['较参考价涨跌',pct(m.ret),signedClass(m.ret),s.ref?`原参考价 ¥ ${money(s.ref)}`:'暂无可靠推荐参考价'],['最高收盘涨跌',pct(m.max),signedClass(m.max),'仅统计推荐后的收盘'],['距最高收盘回落',pct(m.drawdown),signedClass(m.drawdown),'不是历史最大回撤'],['现价仍需上涨',pct(m.remaining),'',s.ref?`至20%目标 ¥ ${money(s.ref*1.2)}`:'目标尚不能计算']];
 const confirmLabel='支持这次走势判断的表现',riskLabel='会改变这次走势判断的表现';
 const events=s.reviews.filter(rv=>rv.date<=C.dateAt(end,DATA)).slice().reverse();
 return `<div class="page-enter"><button class="back-button" data-action="back">${icon('arrow-left')}返回观察清单</button><section class="detail-heading"><div class="stock-title"><span class="stock-token">${escape(s.name[0])}</span><div><h1>${escape(s.name)}</h1><small>${s.code} &nbsp; / &nbsp; ${escape(s.industryName)} &nbsp; / &nbsp; ${s.recDate.replaceAll('-','.')} 推荐</small></div></div><div class="detail-actions">${star(s)}<button class="quiet-btn" data-action="export-record">${icon('download')}导出记录</button><button class="primary-btn" data-action="play" ${s.d0||s.days<1?'disabled':''}>${icon(state.playing?'pause':'play')}<span>${state.playing?'暂停回看':'回放观察过程'}</span></button></div></section>
 <div class="detail-metrics">${fields.map(([label,val,cls,sub])=>`<div class="detail-metric"><div class="label">${label}</div><strong class="num ${cls}">${val}</strong><small>${sub}</small></div>`).join('')}</div>
 <div class="detail-grid"><section class="panel"><div class="detail-chart-head"><h2>价格与成交<span>${C.dateAt(end,DATA).replaceAll('-','.')} / ${s.d0?'待首日观察':`第 ${days} 天`}</span></h2><div class="segmented" aria-label="图表类型">${[['line','收盘走势'],['candle','K 线'],['relative','相对表现']].map(([mode,label])=>`<button class="${state.chartMode===mode?'active':''}" data-chart-mode="${mode}" ${mode==='relative'&&(s.d0||s.ref===null)?'disabled':''}>${label}</button>`).join('')}</div></div><div class="detail-chart-wrap">${plot(s,end,state.chartMode)}</div><div class="chart-subnote">${state.chartMode==='relative'?`<span>首个观察日收盘＝100；与参考价收益口径不同。</span><span class="mini-legend"><span><i class="legend-line"></i>个股</span><span><i class="legend-line" style="background:var(--blue)"></i>${escape(s.industryName)}</span><span><i class="legend-line" style="background:var(--amber)"></i>${escape(DATA.market_name)}</span></span>`:`<span>${state.chartMode==='candle'?'红K：收盘≥开盘 · 绿K：收盘&lt;开盘':'实线：收盘'} &nbsp; 蓝虚线：参考价 &nbsp; 金虚线：20%目标</span><span>下方为成交额，单位：亿元</span>`}${!isLatest?'<span class="accent">正在回看：之后的走势与复盘已隐藏</span>':''}</div><div class="timeline-control"><div class="timeline-top"><span>${s.d0?'首个观察日尚未到达':`正在观察 <b>第 ${days} 天</b> / 20 个交易日`}</span><button class="small-link" data-action="latest" ${isLatest?'disabled':''}>回到最新 ${icon('arrow-right')}</button></div><div class="day-ruler" aria-label="选择观察交易日">${Array.from({length:20},(_,i)=>{const day=i+1,idx=s.recIndex+i,observed=!s.d0&&day<=s.days&&idx<=LAST,changed=s.reviews.some(rv=>rv.day===day&&rv.viewChanged);return `<button class="day-dot ${observed?'observed':''} ${day===days?'active':''} ${changed?'changed':''}" data-day="${day}" ${observed?'':'disabled'} title="${observed?`第${day}天 · ${DATA.dates[idx]}`:`第${day}天尚未观察`}" aria-label="第${day}天${observed?'':'尚未观察'}" aria-pressed="${day===days}">${day.toString().padStart(2,'0')}</button>`}).join('')}</div><div class="timeline-labels"><span>第一天</span><span>小金点＝观点发生变化</span><span>第二十天</span></div>${s.d0?'':`<input class="replay-range" id="replayRange" type="range" min="1" max="${Math.max(1,s.days)}" value="${Math.max(1,days)}" aria-label="拖动回看第几个交易日">`}</div></section>
 <aside class="panel opinion-panel"><span class="eyebrow">REVIEW / 原报告观点 <span>${r?r.date.slice(5).replace('-','.'):'—'}</span></span>${viewPill(r,s.d0?'待首日观察':'没有复盘记录')}<h3>${escape(baseLabel(r))}</h3><p>${escape(r?.outlookReason||(s.d0?'这条记录计划从下一交易日开始观察。现在只能阅读原推荐理由，不能计算推荐后涨跌。':'该条记录未附复盘正文；行情可以查看，但不能用价格自动补出研究结论。'))}</p><div class="opinion-separator"></div><div class="opinion-row"><label>${icon('check')}${confirmLabel}</label><p>${escape(r?.confirm||'原报告本次未填写')}</p></div><div class="opinion-row"><label>${icon('flag')}${riskLabel}</label><p>${escape(r?.risk||'原报告本次未填写')}</p></div><div class="pill-note">${isLatest?`原数据阶段：${escape(s.stage)} · 与研究观点分开保留`:'回看中的阶段仅依据所选日期前的复盘，不套用最新快照阶段。'}${r&&r.date!==C.dateAt(end,DATA)?`<br>所选日没有新复盘，显示最近的 ${r.date} 原记录。`:''}</div><button class="small-link" data-action="read-full">阅读原始判断 ${icon('arrow-right')}</button></aside></div>
 <div class="detail-bottom"><section class="panel" id="reviewPanel"><div class="review-tabs" aria-label="阅读内容"><button class="review-tab ${state.reviewTab==='latest'?'active':''}" data-review-tab="latest">这一天的复盘</button><button class="review-tab ${state.reviewTab==='original'?'active':''}" data-review-tab="original">当初为什么选它</button><button class="review-tab ${state.reviewTab==='company'?'active':''}" data-review-tab="company">公司资料</button></div><div class="review-body">${reviewBody(s,r,end)}</div></section><aside class="panel event-panel"><h3>一路走来的判断</h3><div class="event-list">${events.map(rv=>`<div class="event-item ${rv.viewChanged?'changed':''} ${rv.date===r?.date?'active':''}" data-day="${rv.day}" role="button" tabindex="0"><time>${rv.date.slice(5).replace('-','.')} · 第${rv.day}天 · ${kindLabel(rv)}</time><b>${escape(rv.viewLabel||kindLabel(rv))}</b><p>${escape(rv.viewReason||rv.headline)}</p></div>`).join('')}<div class="event-item" data-review-tab="original" role="button" tabindex="0"><time>${s.recDate.slice(5).replace('-','.')} · ${s.d0?'计划推荐日':'原推荐日'}</time><b>从这个判断开始</b><p>${escape(s.reasonFull)}</p></div></div><p class="source-hint" style="margin-top:23px">只展示当前回看日及之前的记录。<br>全文观点来自原报告，未由DEMO重写。</p></aside></div></div>`;
}
function reviewBody(s,r,end){
 if(state.reviewTab==='original')return `<div class="review-meta"><span>ORIGINAL THESIS</span><span>${s.recDate} · ${escape(s.refKind==='event'?'事件条件记录':'原推荐记录')}</span></div><h3>当时看中的是什么，<br>最担心的又是什么。</h3><div class="copy"><p>${escape(s.reasonFull)}</p></div><div class="original-risk"><h4>原推荐中写下的风险</h4><p>${escape(s.reasonRisk||'原记录未附风险文字。')}</p></div><p class="source-hint">以上为原报告文本。时间轴变化不会改写最初的推荐理由。</p>`;
 if(state.reviewTab==='company')return `<div class="review-meta"><span>COMPANY PROFILE</span><span>来自上传报告</span></div><h3>${escape(s.name)}</h3><div class="copy"><p>${escape(s.company)}</p></div><p class="source-hint">沿用上传快照中的公司资料，未做最新公告或财务核验。</p>`;
 if(!r)return `<div class="empty">${icon('book')}<h3>${s.d0?'第一天的故事，还没开始。':'这一天还没有复盘文字。'}</h3><p>${s.d0?'价格图只展示推荐前的历史走势。':'仅保留源数据已有的价格，不以走势图代写结论。'}</p><button class="quiet-btn" data-review-tab="original">看看当初为什么选择它 ${icon('arrow-right')}</button></div>`;
 const copy=(r.copy||r.summary_copy||'').split(/\n\s*\n/).filter(Boolean);
 return `<div class="review-meta"><span>${r.date.replaceAll('-','.')} / 第${r.day}天</span><span>${kindLabel(r)}</span>${viewPill(r)}</div><h3>${escape(r.headline)}</h3><div class="copy">${copy.map(p=>`<p>${escape(p)}</p>`).join('')}</div>${s.name==='德尔股份'&&r.date==='2026-09-04'?'<div class="warning-note">原文数字提示：本段写“收26.56”，而上传的价格数组中本日收盘为26.65。图表采用价格数组；正文保留原文，没有静默修正。</div>':''}<p class="source-hint">原报告全文保留，包含原有措辞及可能不一致的数字。上方图表与指标仅由价格数组计算。${r.as_of?`<br>原记录生成截止：${escape(r.as_of)}`:''}</p>`;
}
function drawPlot(svg){
 const s=byId(svg.dataset.stock),end=Number(svg.dataset.end),mode=svg.dataset.mode,hero=svg.dataset.hero==='true';
 const W=Math.max(240,svg.clientWidth),H=Math.max(170,svg.clientHeight),small=W<480;
 const pad={l:small?9:15,r:small?46:59,t:30,b:25},volH=hero?0:45,volGap=hero?0:22;
 const priceBottom=H-pad.b-volH-volGap,priceTop=pad.t,plotW=W-pad.l-pad.r;
 const start=mode==='relative'?s.recIndex:0,N=DATA.dates.length-start;
 if(N<1){svg.innerHTML='';return}
 const x=i=>pad.l+(i-start+.5)/N*plotW;
 let closes=s.candles.map(c=>c?.[3]??null),series=[],values=[];
 if(mode==='relative'){
  series=[{values:C.normalize(closes,s.recIndex,end),color:'var(--accent)',name:s.name},
   {values:C.normalize(s.industry,s.recIndex,end),color:'var(--blue)',name:s.industryName},
   {values:C.normalize(DATA.market,s.recIndex,end),color:'var(--amber)',name:DATA.market_name,dashed:true}];
  values=series.flatMap(z=>z.values.slice(start,end+1)).filter(C.valid);
 }else{
  values=s.candles.slice(start,end+1).flatMap(c=>c?(mode==='candle'?[c[1],c[2],c[3]]:[c[3]]):[]).filter(C.valid);
  if(C.valid(s.ref)&&s.ref>0&&!s.d0&&end>=s.recIndex)values.push(s.ref,s.ref*1.2);
 }
 svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
 if(!values.length){svg.innerHTML=`<text x="${W/2}" y="${H/2}" text-anchor="middle" class="chart-label">暂无可靠数据</text>`;return}
 let lo=Math.min(...values),hi=Math.max(...values),span=hi-lo;if(span<.001)span=Math.abs(hi)*.03||1;
 lo-=span*.15;hi+=span*.15;
 const y=v=>priceBottom-(v-lo)/(hi-lo)*(priceBottom-priceTop),gid=`g${++plotId}`;
 const q=C.quoteAt(s,end),px=q?x(q.i):0,py=q?y(mode==='relative'?series[0].values[q.i]:q.c[3]):0;
 const strokeMain='var(--accent-deep)';
 let out=`<defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--accent-deep)" stop-opacity=".19"/><stop offset="100%" stop-color="var(--accent-deep)" stop-opacity="0"/></linearGradient><pattern id="dots-${gid}" x="0" y="0" width="17" height="17" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".6" fill="var(--muted)" opacity=".18"/></pattern></defs>`;
 if(hero)out+=`<rect x="${pad.l}" y="${priceTop}" width="${plotW}" height="${priceBottom-priceTop}" fill="url(#dots-${gid})"/>`;
 for(let j=0;j<=4;j++){const v=lo+(hi-lo)*j/4,yy=y(v);out+=`<line x1="${pad.l}" x2="${W-pad.r+4}" y1="${yy}" y2="${yy}" stroke="var(--border)" stroke-opacity=".58" stroke-dasharray="2 5"/><text x="${W-pad.r+11}" y="${yy+3}" style="font-size:${small?8:9}px;opacity:${q&&mode!=='relative'&&Math.abs(yy-py)<15?0:1}">${mode==='relative'?v.toFixed(1):money(v)}</text>`;}
 const dateIdx=[...new Set(Array.from({length:small?4:6},(_,i)=>start+Math.round(i/((small?4:6)-1)*(N-1))))];
 dateIdx.forEach(i=>{if(i>end)return;const xx=x(i);out+=`<text x="${xx}" y="${H-6}" text-anchor="middle" style="font-size:${small?8:9}px">${DATA.dates[i].replace('-','/')}</text>`});
 if(mode!=='relative'&&!s.d0&&s.ref&&end>=s.recIndex){
  const rx=x(s.recIndex);out+=`<rect x="${rx}" y="${priceTop}" width="${Math.max(0,px-rx)}" height="${priceBottom-priceTop}" fill="var(--accent)" fill-opacity=".018"/>`;
  out+=`<line x1="${pad.l}" x2="${W-pad.r+5}" y1="${y(s.ref)}" y2="${y(s.ref)}" stroke="var(--blue)" stroke-width=".9" opacity=".6" stroke-dasharray="4 5"/>`;
  out+=`<line x1="${rx}" x2="${W-pad.r+5}" y1="${y(s.ref*1.2)}" y2="${y(s.ref*1.2)}" stroke="var(--amber)" opacity=".5" stroke-width=".8" stroke-dasharray="4 5"/><text class="chart-label" x="${W-pad.r-4}" y="${y(s.ref*1.2)-7}" text-anchor="end" style="fill:var(--amber);font-size:${small?8:9}px">20%目标 · ${money(s.ref*1.2)}</text>`;
  out+=`<line x1="${rx}" x2="${rx}" y1="${priceTop+12}" y2="${priceBottom+4}" stroke="var(--blue)" stroke-opacity=".4" stroke-dasharray="2 5"/><circle cx="${rx}" cy="${priceBottom+4}" r="2" fill="var(--blue)"/><text class="chart-label" x="${Math.min(Math.max(rx-5,25),W-pad.r-98)}" y="${18}" style="fill:var(--blue);font-size:${small?8:9}px">${s.recDate.slice(5).replace('-','.')} 开始观察</text>`;
 }
 if(mode==='candle'){
  const width=Math.min(14,plotW/N*.51);
  s.candles.forEach((c,i)=>{if(i<start||i>end||!c||!c.slice(0,4).every(C.valid))return;const color=c[3]>=c[0]?'var(--up)':'var(--down)',alpha=i<s.recIndex?.4:1;out+=`<g opacity="${alpha}"><line x1="${x(i)}" x2="${x(i)}" y1="${y(c[1])}" y2="${y(c[2])}" stroke="${color}" stroke-width="1"/><rect x="${x(i)-width/2}" y="${Math.min(y(c[0]),y(c[3]))}" width="${width}" height="${Math.max(1.3,Math.abs(y(c[0])-y(c[3])))}" fill="${color}" rx=".7"/></g>`});
 }else if(mode==='relative'){
  series.forEach((ser,index)=>{const vals=ser.values.slice(start,end+1),d=simplePath(vals,i=>x(i+start),y);if(!d)return;out+=`<path d="${d}" stroke="${ser.color}" stroke-width="${index===0?2.3:1.35}" fill="none" stroke-linecap="round" stroke-linejoin="round" ${ser.dashed?'stroke-dasharray="4 4"':''}/>`;});
  const missing=!series[1].values.some(C.valid);out+=`<text class="chart-label" x="${pad.l+3}" y="17" style="fill:var(--secondary);font-size:9px">${missing?'行业数据缺失，未绘制行业线':'以首个观察日收盘为100'}</text>`;
 }else{
  const a=closes.slice(start,end+1),d=simplePath(a,i=>x(i+start),y);
  out+=`<path d="${d}" stroke="${strokeMain}" stroke-opacity="${s.d0?'.75':'.26'}" stroke-width="1.7" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`;
  const postStart=s.d0?start:Math.max(start,s.recIndex),post=closes.slice(postStart,end+1),good=post.filter(C.valid);
  if(good.length){const dpost=simplePath(post,i=>x(i+postStart),y);if(post.every(C.valid)&&post.length>1){out+=`<path d="${dpost}L${x(end)},${priceBottom} L${x(postStart)},${priceBottom}Z" fill="url(#${gid})"/>`}
   out+=`<path class="${hero?'chart-line chart-glow':''}" d="${dpost}" fill="none" stroke="var(--accent)" stroke-width="${hero?2.25:2}" stroke-linecap="round" stroke-linejoin="round"/>`;
   if(q&&C.valid(py)){out+=`<circle class="${hero?'chart-point-pulse':''}" cx="${px}" cy="${py}" r="11" fill="var(--accent)" fill-opacity=".17"/><circle cx="${px}" cy="${py}" r="4" fill="var(--panel)" stroke="var(--accent)" stroke-width="2"/>`;}
  }
 }
 if(q&&q.i>=start&&C.valid(py)&&mode!=='relative'){
  out+=`<line x1="${px+5}" x2="${W-pad.r+5}" y1="${py}" y2="${py}" stroke="var(--accent)" opacity=".25" stroke-dasharray="3 4"/><rect x="${W-pad.r+6}" y="${py-9}" width="${pad.r-8}" height="18" rx="3" fill="var(--accent)"/><text x="${W-pad.r+11}" y="${py+3}" style="fill:var(--bg);font-size:${small?8:9}px">${money(q.c[3])}</text>`;
 }
 if(!hero){
  const vt=priceBottom+volGap,vb=H-pad.b,amounts=s.candles.slice(start,end+1).map(c=>c?.[4]).filter(C.valid),maxV=Math.max(...amounts,1),barW=Math.max(2,Math.min(13,plotW/N*.5));
  out+=`<line x1="${pad.l}" x2="${W-pad.r}" y1="${vt-9}" y2="${vt-9}" stroke="var(--border)" opacity=".5"/><text class="chart-label" x="${pad.l}" y="${vt-14}" style="font-size:8px">成交额 / 亿元</text>`;
  s.candles.forEach((c,i)=>{if(i<start||i>end||!c||!C.valid(c[4]))return;const h=Math.max(1,c[4]/maxV*volH),color=c[3]>=c[0]?'var(--up)':'var(--down)';out+=`<rect x="${x(i)-barW/2}" y="${vb-h}" width="${barW}" height="${h}" rx="1" fill="${color}" opacity="${i<s.recIndex?.19:.42}"/>`});
 }
 if(end<LAST){const fx=x(end)+(plotW/N)/2,fw=W-pad.r-fx;if(fw>105)out+=`<text class="chart-label" x="${fx+fw/2}" y="${priceTop+(priceBottom-priceTop)/2}" text-anchor="middle" style="font-size:9px;opacity:.6">后续走势已隐藏</text>`;}
 out+=`<g class="floating-crosshair"></g>`;
 svg.innerHTML=out;
 svg.onpointermove=e=>{
  const rect=svg.getBoundingClientRect(),local=e.clientX-rect.left,idx=start+Math.floor((local-pad.l)/plotW*N);
  if(idx<start||idx>end||!s.candles[idx]||!C.valid(s.candles[idx][3])){hideTip();svg.querySelector('.floating-crosshair').innerHTML='';return}
  const c=s.candles[idx],xx=x(idx),yy=y(mode==='relative'?series[0].values[idx]:c[3]);
  svg.querySelector('.floating-crosshair').innerHTML=`<line x1="${xx}" x2="${xx}" y1="${priceTop}" y2="${H-pad.b}" stroke="var(--secondary)" stroke-dasharray="3 4" opacity=".7"/>${C.valid(yy)?`<circle cx="${xx}" cy="${yy}" r="4" fill="var(--panel)" stroke="var(--accent)"/>`:''}`;
  const ret=C.metrics(s,idx).ret;
  const norm=mode==='relative'?`<div><dt>个股（归一）</dt><dd>${money(series[0].values[idx])}</dd></div><div><dt>${escape(s.industryName)}</dt><dd>${money(series[1].values[idx])}</dd></div><div><dt>${escape(DATA.market_name)}</dt><dd>${money(series[2].values[idx])}</dd></div>`:'';
  showTip(`<b>${escape(s.name)} · ${DATA.dates[idx].replace('-','/')}</b><dl><div><dt>开盘 / 收盘</dt><dd>${money(c[0])} / ${money(c[3])}</dd></div><div><dt>最高 / 最低</dt><dd>${money(c[1])} / ${money(c[2])}</dd></div><div><dt>成交额</dt><dd>${money(c[4])} 亿</dd></div><div><dt>较参考价</dt><dd class="${signedClass(ret)}">${pct(ret)}</dd></div>${norm}</dl>`,e);
 };
 svg.onpointerleave=()=>{hideTip();svg.querySelector('.floating-crosshair').innerHTML=''};
 svg.onkeydown=e=>{if(state.page==='detail'&&['ArrowLeft','ArrowRight'].includes(e.key)&&!s.d0){e.preventDefault();stopPlayback();const newEnd=Math.max(s.recIndex,Math.min(LAST,state.end+(e.key==='ArrowRight'?1:-1)));state.end=newEnd;render(false);document.querySelector('.main-plot')?.focus()}};
}
function drawAtlas(){
 const svg=$('atlas');if(!svg)return;
 const W=svg.clientWidth,H=svg.clientHeight,small=W<500,pad={l:small?35:46,r:small?24:45,t:36,b:42};
 const list=stocks.map(s=>({s,m:C.metrics(s,LAST)})).filter(x=>x.m.ret!==null),maxDays=Math.max(...list.map(x=>x.s.days))+1;
 if(!list.length){svg.innerHTML='<text x="40" y="70" class="chart-label">暂无可计算的参考价记录</text>';return}
 const x=day=>pad.l+day/maxDays*(W-pad.l-pad.r),y=ret=>H-pad.b-(ret+12)/24*(H-pad.t-pad.b);
 svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
 let out=`<defs><radialGradient id="atlas-glow"><stop offset="0" stop-color="var(--accent)" stop-opacity=".07"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></radialGradient><pattern id="atlas-dots" width="18" height="18" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".6" fill="var(--muted)" opacity=".24"/></pattern></defs><rect x="${pad.l}" y="${pad.t}" width="${W-pad.l-pad.r}" height="${H-pad.t-pad.b}" fill="url(#atlas-dots)"/>`;
 [-10,-5,0,5,10].forEach(v=>{out+=`<line x1="${pad.l}" x2="${W-pad.r}" y1="${y(v)}" y2="${y(v)}" stroke="${v===0?'var(--secondary)':'var(--border)'}" stroke-dasharray="${v===0?'5 5':'2 6'}" opacity="${v===0?.5:.7}"/><text x="${pad.l-9}" y="${y(v)+3}" text-anchor="end" style="font-size:${small?8:9}px">${v>0?'+':''}${v}%</text>`});
 for(let d=2;d<=maxDays;d+=2){out+=`<line x1="${x(d)}" x2="${x(d)}" y1="${pad.t}" y2="${H-pad.b}" stroke="var(--border)" opacity=".45"/><text x="${x(d)}" y="${H-pad.b+20}" text-anchor="middle" style="font-size:9px">${d}</text>`;}
 out+=`<text class="chart-label" x="${pad.l}" y="18" style="font-size:9px">较原参考价涨跌</text><text class="chart-label" x="${W-pad.r}" y="${H-5}" text-anchor="end" style="font-size:9px">观察天数 →</text><text x="${pad.l+10}" y="${y(0)-9}" class="chart-label" style="font-size:8px;opacity:.6">原参考价</text>`;
 const labels=new Set(['银龙股份','中国船舶','舒泰神','德尔股份','中航西飞','闰土股份']);
 list.sort((a,b)=>(C.quoteAt(b.s,LAST)?.c[4]||0)-(C.quoteAt(a.s,LAST)?.c[4]||0)).forEach(({s,m})=>{
  const xx=x(s.days),yy=y(m.ret),amt=C.quoteAt(s,LAST)?.c[4]||0,radius=Math.min(small?10:13,3+Math.sqrt(Math.max(0,amt))*1.15),col=m.ret>=0?'var(--up)':'var(--down)',active=C.key(s)===state.mapCurrent;
  out+=`<g class="map-dot" data-map-id="${C.key(s)}" data-open="${C.key(s)}" tabindex="0" role="button" aria-label="${escape(s.name)} ${s.recDate}，第${s.days}天，较参考价${pct(m.ret)}"><circle cx="${xx}" cy="${yy}" r="${radius+9}" fill="${col}" opacity=".06"/><circle cx="${xx}" cy="${yy}" r="${radius+4}" fill="none" stroke="${col}" stroke-opacity="${active?.55:.12}"/><circle class="bubble-core" cx="${xx}" cy="${yy}" r="${radius}" fill="${col}" fill-opacity="${active?.7:.35}" stroke="${col}" stroke-opacity=".8" stroke-width=".9"/><circle cx="${xx}" cy="${yy}" r="1.5" fill="${col}"/>`;
  if(labels.has(s.name)&&(!small||s.name!=='中航西飞')&&!(s.name==='中国船舶'&&s.days===5)){
   const align=s.days>=9?'end':'start',tx=s.days>=9?xx-radius-9:xx+radius+9,ty=s.name==='德尔股份'?yy+16:yy-7;
   out+=`<text x="${tx}" y="${ty}" text-anchor="${align}" class="chart-label" style="fill:var(--secondary);font-size:${small?8:10}px">${escape(s.name)}</text>`;
  }
  out+='</g>';
 });
 svg.innerHTML=out;
 svg.onpointermove=e=>{const dot=e.target.closest('.map-dot');if(!dot){hideTip();return}const s=byId(dot.dataset.mapId),m=C.metrics(s,LAST);showTip(`<b>${escape(s.name)} · ${s.recDate}</b><dl><div><dt>观察进度</dt><dd>第 ${s.days} 天</dd></div><div><dt>较参考价</dt><dd class="${signedClass(m.ret)}">${pct(m.ret)}</dd></div><div><dt>成交额</dt><dd>${money(C.quoteAt(s,LAST)?.c[4])} 亿</dd></div></dl><div class="source-hint" style="margin-top:5px">点击进入这次观察</div>`,e);if(state.mapCurrent!==C.key(s)){state.mapCurrent=C.key(s);$('mapSelection').innerHTML=mapSelection(s)}};
 svg.onpointerleave=hideTip;
}
function showTip(html,e){const el=$('tooltip');el.innerHTML=html;el.style.display='block';const w=el.offsetWidth,h=el.offsetHeight;el.style.left=`${Math.max(10,Math.min(window.innerWidth-w-10,e.clientX+17))}px`;el.style.top=`${Math.max(10,Math.min(window.innerHeight-h-10,e.clientY+17))}px`}
function hideTip(){$('tooltip').style.display='none'}
function toast(msg){clearTimeout(toastTimer);$('toast').textContent=msg;$('toast').classList.add('show');toastTimer=setTimeout(()=>$('toast').classList.remove('show'),2300)}
function refreshCounts(){$('favCount').textContent=state.favorites.size;$('recordCount').textContent=stocks.length}
function draw(){document.querySelectorAll('.main-plot').forEach(drawPlot);drawAtlas()}
function render(scroll=false){
 hideTip();
 const names={overview:'总览工作台',records:'全部观察',map:'观察星图',journal:'观点时间线',favorites:'我的收藏',detail:'个股复盘'};
 $('breadcrumb').textContent=names[state.page];
 document.querySelectorAll('.nav-item').forEach(b=>{const active=b.dataset.nav===state.page||(state.page==='detail'&&b.dataset.nav==='records');b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
 $('content').innerHTML=!stocks.length?`<div class="page-enter">${intro('AFTER THE CLOSE / BEFORE THE NEXT MOVE','暂无观察记录。','本次快照没有观察记录，不填入示例股票，也不生成新的判断。')}<section class="panel"><div class="empty">${icon('layers')}<h3>暂无观察记录</h3><p>接入一份包含观察记录的快照后，页面会在原位置展示内容。</p></div></section></div>`:state.page==='overview'?overview():state.page==='map'?mapPage():state.page==='journal'?journal():state.page==='detail'?detail():records();
 hydrate();refreshCounts();draw();
 document.dispatchEvent(new CustomEvent("guanlan:render",{detail:{page:state.page}}));
 if(scroll){window.scrollTo({top:0,behavior:'instant'});$('content').focus({preventScroll:true});}
 document.title=state.page==='detail'?`${byId(state.current).name} · 观澜 · 光场 PRISM`:'观澜 · 光场 PRISM — 收盘之后，看清变化';
}
function stopPlayback(){if(playback)clearInterval(playback);playback=null;state.playing=false}
let returnPage='overview';
function navigate(page){stopPlayback();if(page!==state.page){state.filter='all';state.query=''}state.page=page;render(true)}
function openStock(id,end=LAST){const s=byId(id);if(!s)return;stopPlayback();if(state.page!=='detail')returnPage=state.page;state.current=id;state.end=Math.max(s.d0?LAST:s.recIndex,Math.min(LAST,end));state.chartMode='line';state.reviewTab='latest';state.page='detail';closeDialogs();render(true)}
function setDay(day,rerender=true){const s=byId(state.current);if(s.d0||day<1||day>s.days)return;state.end=Math.min(LAST,s.recIndex+day-1);if(rerender)render(false)}
// Update the day without replacing the native range input during a drag.
function refreshDetailDay(){
 const temp=document.createElement('div');temp.innerHTML=detail();
 for(const selector of ['.detail-metrics','.detail-chart-head','.detail-chart-wrap','.chart-subnote','.opinion-panel','.review-body','.event-panel']){
  const current=$('content').querySelector(selector),next=temp.querySelector(selector);
  if(current&&next)current.replaceWith(next);
 }
 const s=byId(state.current),day=C.daysAt(s,state.end);
 const top=$('content').querySelector('.timeline-top'),newTop=temp.querySelector('.timeline-top');if(top&&newTop)top.replaceWith(newTop);
 $('content').querySelectorAll('.day-dot').forEach(b=>{const active=Number(b.dataset.day)===day;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
 const playButton=$('content').querySelector('[data-action="play"]');if(playButton)playButton.innerHTML=icon('play')+'<span>回放观察过程</span>';
 draw();
}
function play(){
 const s=byId(state.current);if(s.d0)return;
 if(state.playing){stopPlayback();render(false);return}
 state.playing=true;
 if(state.end>=LAST)state.end=s.recIndex;
 render(false);
 playback=setInterval(()=>{if(state.end>=LAST){stopPlayback();render(false);toast('已回看到快照最后一个交易日');return}state.end++;render(false)},1450);
}
function toggleStar(id){
 if(state.favorites.has(id))state.favorites.delete(id);else state.favorites.add(id);
 writeStore('guanlan.favorites',JSON.stringify([...state.favorites]));
 document.querySelectorAll('[data-star]').forEach(btn=>{if(btn.dataset.star!==id)return;const saved=state.favorites.has(id);btn.classList.toggle('saved',saved);btn.setAttribute('aria-pressed',String(saved));btn.setAttribute('aria-label',`${saved?'取消收藏':'收藏'}${byId(id).name}`)});
 refreshCounts();if(state.page==='favorites')render(false);toast(state.favorites.has(id)?'已加入我的收藏':'已取消收藏');
}
function downloadData(single=false){
 const s=byId(state.current),date=single?C.dateAt(state.end,DATA):DATA.analysis_date;
 // A historical record export excludes later price/review entries; no hidden future data.
 const data=single?{...s,days:C.daysAt(s,state.end),...(state.end<LAST?{stage:null,stageType:null,attention:null,trigger:null,suspended:null}:{}),candles:s.candles.slice(0,state.end+1),industry:s.industry.slice(0,state.end+1),reviews:s.reviews.filter(r=>r.date<=date),events:s.events.filter(e=>`${DATA.analysis_date.slice(0,4)}-${e[0]}`<=date)}:DATA;
 const payload={demo:'观澜 · 光场 PRISM',source:'用户上传的观察日报V4，未经外部核验',price_through:date,...(single?{record:data}:{snapshot:data})};
 const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=url;a.download=single?`guanlan-${s.code}-${s.recDate}-through-${date}.json`:`guanlan-snapshot-${date}.json`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(single?'已导出所选时点的观察记录':'已导出完整快照');
}
function closeDialogs(){document.querySelectorAll('dialog[open]').forEach(d=>d.close());document.body.classList.remove('modal-open')}
function searchResults(){
 const q=$('commandInput').value.trim().toLowerCase();
 state.searchList=stocks.filter(s=>!q||`${s.name} ${s.code} ${s.industryName} ${s.recDate}`.toLowerCase().includes(q)).slice(0,q?35:8);
 state.searchIndex=Math.max(0,Math.min(state.searchIndex,state.searchList.length-1));
 $('searchResults').innerHTML=state.searchList.length?state.searchList.map((s,i)=>{const m=C.metrics(s,LAST);return `<button class="search-result ${i===state.searchIndex?'active':''}" data-open="${C.key(s)}"><span class="stock-token sm">${escape(s.name[0])}</span><span class="search-info"><strong>${escape(s.name)}</strong><small>${s.code} · ${s.recDate} 推荐 · ${escape(s.industryName)}</small></span><span class="num ${signedClass(m.ret)}">${pct(m.ret)}</span>${icon('arrow-up-right')}</button>`}).join(''):`<div class="empty"><h3>没有找到匹配记录</h3><p>试试股票名称、六位代码或行业名称。</p></div>`;
}
function openSearch(){stopPlayback();$('commandInput').value='';state.searchIndex=0;searchResults();$('searchDialog').showModal();document.body.classList.add('modal-open');$('commandInput').focus()}
function openInfo(){$('infoDialog').showModal();document.body.classList.add('modal-open')}
function changeTheme(){document.body.classList.toggle('light');writeStore('guanlan.theme',document.body.classList.contains('light')?'light':'dark');draw()}
// The file deliberately uses event delegation: every visible action has one local handler.
document.addEventListener('click',e=>{
 const el=e.target.closest('button,[data-open],[data-day],[data-review-tab]');if(!el||el.disabled)return;
 if(el.dataset.star){e.stopPropagation();toggleStar(el.dataset.star);return}
 if(el.dataset.open){openStock(el.dataset.open,el.dataset.openEnd?Number(el.dataset.openEnd):LAST);return}
 if(el.dataset.nav){navigate(el.dataset.nav);return}
 if(el.dataset.heroStep){state.hero=(state.hero+Number(el.dataset.heroStep)+heroStocks.length)%heroStocks.length;render(false);return}
 if(el.dataset.cardMode){state.cardMode=el.dataset.cardMode;render(false);return}
 if(el.dataset.filter){state.filter=el.dataset.filter;render(false);return}
 if(el.dataset.sort){if(state.sort===el.dataset.sort)state.direction*=-1;else{state.sort=el.dataset.sort;state.direction=-1}render(false);return}
 if(el.dataset.chartMode){state.chartMode=el.dataset.chartMode;render(false);return}
 if(el.dataset.day){stopPlayback();setDay(Number(el.dataset.day));return}
 if(el.dataset.reviewTab){state.reviewTab=el.dataset.reviewTab;const y=window.scrollY;render(false);window.scrollTo({top:y,behavior:'instant'});return}
 if(el.dataset.journalMode){state.onlyChanges=el.dataset.journalMode==='changes';render(false);return}
 switch(el.dataset.action){
  case'search':openSearch();break;
  case'info':openInfo();break;
  case'close-dialog':closeDialogs();break;
  case'theme':changeTheme();break;
  case'focus':document.body.classList.toggle('focus-mode');draw();break;
  case'export':downloadData();break;
  case'export-record':downloadData(true);break;
  case'play':play();break;
  case'latest':stopPlayback();state.end=LAST;render(false);break;
  case'back':navigate(returnPage);break;
  case'attention':navigate('records');state.filter='attention';render(false);break;
  case'positive':navigate('records');state.filter='positive';render(false);break;
  case'read-full':state.reviewTab='latest';render(false);$('reviewPanel').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});break;
 }
});
document.addEventListener('input',e=>{
 if(e.target.id==='recordSearch'){state.query=e.target.value;$('tableRows').innerHTML=tableRows();$('tableEmpty').hidden=filteredStocks().length>0;$('tableCount').textContent=`${filteredStocks().length} 条记录`;}
 if(e.target.id==='commandInput'){state.searchIndex=0;searchResults();}
 if(e.target.id==='replayRange'){const day=Number(e.target.value);stopPlayback();setDay(day,false);refreshDetailDay();}
});
document.addEventListener('change',e=>{if(e.target.id==='journalDate'){state.journalDate=e.target.value;render(false)}});
document.addEventListener('keydown',e=>{
 const typing=['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName),modal=!!document.querySelector('dialog[open]');
 if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();if($('searchDialog').open)closeDialogs();else if(!modal)openSearch();return}
 if($('searchDialog').open){if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();state.searchIndex=(state.searchIndex+(e.key==='ArrowDown'?1:-1)+state.searchList.length)%Math.max(1,state.searchList.length);searchResults();$('searchResults').querySelector('.active')?.scrollIntoView({block:'nearest'});}if(e.key==='Enter'&&e.target.id==='commandInput'&&state.searchList[state.searchIndex]){e.preventDefault();openStock(C.key(state.searchList[state.searchIndex]));}return}
 if(modal)return;
 if(!typing&&['1','2','3','4'].includes(e.key)){navigate({1:'overview',2:'records',3:'map',4:'journal'}[e.key]);return}
 if(!typing&&e.key==='/'){e.preventDefault();openSearch();return}
 if(['Enter',' '].includes(e.key)&&e.target.matches('[role="button"]:not(button)')){e.preventDefault();e.target.click();}
});
document.querySelectorAll('dialog').forEach(d=>{d.addEventListener('close',()=>{if(!document.querySelector('dialog[open]'))document.body.classList.remove('modal-open')});d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeDialogs()}})});
window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(draw,100)});
document.addEventListener('visibilitychange',()=>{if(document.hidden){stopPlayback();if(state.page==='detail')render(false)}});
if(readStore('guanlan.theme')==='light')document.body.classList.add('light');
// Bind snapshot metadata; never leave the demo's date/count in a new report.
const footerNode=$('snapshotFooter'),summaryNode=$('snapshotSummary'),timingNode=$('snapshotTiming');
if(footerNode)footerNode.textContent=`上传报告快照 · 行情截至 ${displayDate} · 非实时行情，非账户收益`;
if(summaryNode)summaryNode.textContent=`这是基于上传的观察日报制作的独立交互展示稿。载入${stocks.length}条观察记录，不访问网络、不连接券商，也不生成新的选股结论。`;
if(timingNode)timingNode.textContent=`行情截至${DATA.analysis_date}。原快照截止为${DATA.as_of||'源报告未提供'}。逐日回看按复盘日期展示；部分报告在之后生成，因此这不是严格按当时可见信息运行的历史回测。`;
hydrate();refreshCounts();render();
// Exposed read-only inspection hooks for the included tests, not an external API.
window.GUANLAN={snapshot:DATA,getState:()=>({...state,favorites:[...state.favorites]}),core:C};
})();
