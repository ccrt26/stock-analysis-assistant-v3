/* 观澜 · PRISM V3 standalone presentation demo. All content stays local. */
(function(){
'use strict';
const DATA=JSON.parse(document.getElementById('snapshot').textContent);
const R=window.GuanlanRules;
const C=window.GuanlanCore, LAST=DATA.dates.length-1, stocks=DATA.stocks;
// 日期合同守卫：sessionDates 缺失且旧 MM-DD 无法证明年份时拒绝显示，不猜年份。
let DATE_ERROR=null;
try{C.resolveDates(DATA)}catch(error){DATE_ERROR=error.message}
const $=id=>document.getElementById(id);
const escape=t=>String(t??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const pct=v=>C.valid(v)?`${v>0?'+':''}${Math.abs(v)<0.00001?'0.00':v.toFixed(2)}%`:'—';
const money=v=>C.valid(v)?v.toFixed(2):'—';
const signedClass=v=>!C.valid(v)||Math.abs(v)<1e-8?'secondary':v>0?'positive':'negative';
const byId=id=>stocks.find(s=>C.key(s)===id);
const readStore=k=>{try{return localStorage.getItem(k)}catch{return null}};
const writeStore=(k,v)=>{try{localStorage.setItem(k,v);return true}catch{return false}};
let favorites=[];try{favorites=JSON.parse(readStore('guanlan.favorites')||'[]');if(!Array.isArray(favorites))favorites=[]}catch{}
if(DATE_ERROR){
 // 只输出拒绝说明；不做任何带年份假设的计算，也不显示半页假成功。
 $('content').innerHTML=`<div class="page-enter"><section class="panel"><div class="empty">${'<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></svg>'}<h3>快照日期无法定位，页面拒绝显示</h3><p>${DATE_ERROR.replace(/&/g,'&amp;').replace(/</g,'&lt;')}</p><p>请从原归档重新生成展示数据（需要完整 ISO sessionDates 或自洽的同年 MM-DD）。</p></div></section></div>`;
 document.title='观澜 · 光场 PRISM — 快照日期无法定位';
 return;
}
// The current day's upstream ordinary-deep review selection, at most 8 companies.
const presentation=DATA.presentation||{};
const deepSelection=R.deepReviews(DATA), deepGroups=deepSelection.groups;
// 只读观察口径（20个交易日 / 20%观察目标）：来自生成器的 observationPolicy，
// 缺失时用同一命名默认；页面只读，不提供修改历史目标的开关。
const POLICY=DATA.observationPolicy||{};
const OBS={
 days:Number.isFinite(POLICY.primaryDays)&&POLICY.primaryDays>0?Math.floor(POLICY.primaryDays):20,
 target:Number.isFinite(POLICY.targetReturn)&&POLICY.targetReturn>0?POLICY.targetReturn:0.2};
const targetPrice=s=>C.valid(s.ref)?s.ref*(1+OBS.target):null;
const sourceLabel=()=>DATA.sourceInfo?.label||'来源未知';
const heroStocks=deepGroups.map(g=>g.records[0].s);
const displayDate=DATA.analysis_date.replaceAll('-','.');
const displayWeekday=['SUN','MON','TUE','WED','THU','FRI','SAT'][new Date(DATA.analysis_date+'T12:00:00Z').getUTCDay()]||'';
const state={page:'overview',query:'',sort:'date',direction:-1,hero:0,heroRecord:0,railLeft:0,filters:R.defaultFilters(),journalMode:'directions',
  current:stocks.length?C.key(heroStocks[0]||stocks[0]):'',end:LAST,chartMode:'line',reviewTab:'latest',journalDate:DATA.analysis_date,
  // 星图两种选中状态分开保存：股票视图用代码，记录视图用原记录键 code:recDate。
  mapMode:'stock',mapGroup:null,mapCurrent:null,mapPreview:null,favorites:new Set(favorites),searchIndex:0,searchList:[],playing:false};
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
function viewPill(r,fallback='尚未复盘'){
 // 颜色/归类走结构化枚举（viewCode）；旧快照按精确中文映射。未知枚举显示“未识别状态”，
 // 不退回“维持原判/尚未复盘”，也不从涨跌或关键词猜。
 const code=R.viewCode(r);
 let label=r?.viewLabel||fallback;
 if(r&&code==='unrecognized'&&!r.viewLabel)label='未识别状态';
 const cls=code&&['invalidated','strengthened','weakened','maintained'].includes(code)
  ?{invalidated:'invalid',strengthened:'support',weakened:'weak',maintained:'partial'}[code]
  :label==='判断失效'||label==='原判断失效'?'invalid':label==='观点增强'?'support':label==='观点减弱'?'weak':label==='维持原判断'||label==='维持原判'?'partial':'neutral';
 return `<span class="pill ${cls}">${['观点增强','观点减弱','判断失效'].includes(label)?icon(label==='观点增强'?'trend':label==='判断失效'?'close':'minus'):''}${escape(label)}</span>`;
}
function ledgerPill(s){return viewPill({viewLabel:R.opinionLabel(s,DATA)})}
function baseLabel(r){return r?r.base.replace(/^未来1—3个交易日更可能/,'').replace(/^先等待事件或复牌后的实际交易反应，方向暂时无法判断$/,'等待实际交易反应'):'尚无复盘观点'}
// 复盘三路：节点详评 / 普通详评 / 简评；未知类型按源数据原样标注为完整复盘。
function kindLabel(r){return !r?'':r.review_kind==='checkpoint_detail'?'节点详评':r.review_kind==='brief'?'简评':r.review_kind==='regular_detail'?'普通详评':'完整复盘'}
// 停止主动跟踪：以源快照 tracking_status／tracking_exit_date 为准，不由展示层推断。
const dotDate=v=>String(v).replaceAll('-','.');
const stoppedTracking=s=>s.trackingStatus==='evaluation_only'||!!s.trackingExitDate;
const lastReviewOf=s=>[...(s.reviews||[])].sort((a,b)=>a.day-b.day).at(-1)||null;
function star(s){const saved=state.favorites.has(C.key(s));return `<button class="icon-btn star-button ${saved?'saved':''}" data-star="${C.key(s)}" aria-label="${saved?'取消收藏':'收藏'}${escape(s.name)}" aria-pressed="${saved}">${icon('star')}</button>`}
// 回放尺用只读口径 primaryDays 渲染；记录明确已有超出天数（延长观察）时如实显示既有数据，
// 不新增延长判断，不重算或改写第 20 天结论。
function rulerLength(s){return Math.max(OBS.days,s.days||0)}
function progress(s,end=LAST){return s.d0?'待首日观察':`第 ${C.daysAt(s,end)} 天 <span class="muted">/ ${OBS.days}</span>`}
// 事件日期：新生成事件为完整 ISO；旧事件 MM-DD 只按 dates 同一序号受约束转换，定位不到就排除。
function eventISO(e){
 if(typeof e?.[0]==='string'&&e[0].length===10)return e[0];
 const i=DATA.dates.indexOf(e?.[0]);
 return i>=0?C.dateAt(i,DATA):null;
}
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
// formedOn=推荐形成日（盘后报告日）；缺失时（demo快照）回退显示行动日，仍称“入选”。
function dateWord(s){return s.formedOn?{d:s.formedOn,w:'推荐'}:{d:s.recDate,w:'入选'}}
function card(s){
 const m=R.returnOnDate(s,DATA);
 return `<article class="observation-card" data-open="${C.key(s)}" tabindex="0" role="button" aria-label="查看${escape(s.name)} ${dateWord(s).d}${dateWord(s).w}记录"><div class="card-top"><div><h3 class="card-name">${escape(s.name)}</h3><div class="card-code">${s.code}</div></div>${star(s)}</div><div class="card-price-row"><strong class="num ${signedClass(m)}">${pct(m)}</strong>${spark(s)}</div><div class="card-caption">${s.d0?'尚未开始观察 · 小图为首日观察前走势':m===null?'本日无可计算的参考价表现':'收盘较原参考价'}</div><div class="card-bottom">${ledgerPill(s)}<span>${progress(s)}</span></div><div class="card-recommended">${dateWord(s).w}日期 <time>${dateWord(s).d.replaceAll('-','.')}</time>${s.refKind==='event'?'<span>事件条件记录</span>':''}</div></article>`;
}
function currentChanges(date=DATA.analysis_date){return stocks.flatMap(s=>s.reviews.filter(r=>r.date===date&&r.viewChanged).map(r=>({s,r})))}
function marketSpark(row){
 const vals=row.series.slice(-20),good=vals.filter(C.valid);
 if(good.length<2)return '';
 const lo=Math.min(...good),span=Math.max(...good)-lo||1;
 const d=simplePath(vals,i=>2+i/Math.max(1,vals.length-1)*100,v=>29-(v-lo)/span*25);
 return `<svg class="market-spark" viewBox="0 0 104 34" aria-label="近期日线收盘走势"><path d="${d}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}
function marketSection(){
 const rows=R.marketCards(DATA),ready=rows.filter(x=>x.close!==null).length;
 return `<section class="market-section" aria-label="当日市场概览"><div class="market-caption"><span>当日市场 <small>MARKET OVERVIEW</small></span><span>${DATA.analysis_date} 收盘 · ${ready}/${rows.length} 项已提供${ready<rows.length?' <button class="text-button" data-action="market-info">缺项说明 ↗</button>':''}</span></div><div class="stats-grid market-grid" style="--market-count:${rows.length}">${rows.map(row=>`<article class="stat-card market-card ${row.close===null?'market-missing':''}" data-index="${row.code}"><div class="stat-title"><span>${escape(row.name)}</span><span class="index-code">${row.code}</span></div><div class="market-value num">${row.close===null?'—':money(row.close)}<span>点</span></div><div class="market-price-change ${signedClass(row.changePct)}">${row.close===null?`<span class="missing-label">${row.status==='stale'?'本日行情待更新':'快照未提供'}</span>`:`<b class="num">${pct(row.changePct)}</b><span class="num">${row.change===null?'无前收对照':`${row.change>0?'+':''}${money(row.change)} 点`}</span>`}${marketSpark(row)}</div><div class="market-card-foot"><span>${escape(row.description)}</span><span>${row.close!==null?'收盘快照':'待接入'}</span></div></article>`).join('')}</div></section>`;
}
function deepFocus(){
 const group=deepGroups[state.hero],item=group?.records[state.heroRecord]||group?.records[0];
 if(!item)return `<section class="panel hero-panel deep-empty"><div class="panel-head"><h2 class="panel-heading">${icon('pulse')}走势聚焦</h2><span class="deep-count">当日深度复盘 · 0 只</span></div><div class="empty">${icon('book')}<h3>本日没有选入普通深度复盘的股票</h3><p>节点详评和简评仍可从推荐股票清单查看。<br>不以近期推荐或历史记录补足名额。</p></div></section>`;
 const {s,r}=item,m=C.metrics(s,LAST),hasRef=C.valid(s.ref)&&s.ref>0&&!s.d0;
 return `<section class="panel hero-panel" data-deep-code="${s.code}" data-deep-record="${C.key(s)}"><div class="panel-head"><div class="panel-heading">${icon('pulse')}走势聚焦 <small>DEEP REVIEW</small></div><button class="small-link" data-open="${C.key(s)}">进入完整复盘 ${icon('arrow-up-right')}</button></div><div class="deep-toolbar"><span class="deep-count"><i></i>当日深度复盘 · ${deepGroups.length} 只</span></div><div class="hero-top"><div class="stock-title"><div><h2>${escape(s.name)}</h2><small>${s.code} <span> · ${dateWord(s).d.replaceAll('-','.')} ${dateWord(s).w}</span></small></div></div><div class="hero-metric"><strong class="num ${signedClass(m.ret)}">${pct(m.ret)}</strong><small>第 ${r.day} 个交易日 · 收盘较参考价</small></div></div>${group.records.length>1?`<div class="episode-switch"><label for="deepEpisode">这只股票的推荐记录</label><select id="deepEpisode" class="select-input">${group.records.map((x,i)=>`<option value="${i}" ${i===state.heroRecord?'selected':''}>${dateWord(x.s).d} ${dateWord(x.s).w}</option>`).join('')}</select></div>`:''}<div class="hero-summary">${viewPill(r)}<span>${escape(r.viewReason||r.headline)}</span></div><div class="hero-outlook"><span>未来 1—3 个交易日</span><b>${escape(baseLabel(r))}</b></div><div class="hero-chart">${plot(s,LAST,'line',true)}</div><div class="hero-foot"><div class="mini-legend"><span><i class="legend-line"></i>收盘价</span>${hasRef?`<span><i class="legend-line dashed"></i>推荐参考价</span><span><i class="legend-line target"></i>${Math.round(OBS.target*100)}%观察目标</span>`:''}</div><div class="hero-cycle"><span>${String(state.hero+1).padStart(2,'0')} / ${String(deepGroups.length).padStart(2,'0')}</span><button class="icon-btn" data-hero-step="-1" aria-label="上一只深度复盘股票" ${deepGroups.length<2?'disabled':''}>${icon('chevron-left')}</button><button class="icon-btn" data-hero-step="1" aria-label="下一只深度复盘股票" ${deepGroups.length<2?'disabled':''}>${icon('chevron-right')}</button></div></div><div class="deep-source">${deepSelection.overflow?`源记录有 ${deepSelection.totalStocks} 只普通详评，按源顺序展示上限 ${deepSelection.limit} 只。`:'名单来自本日普通详评；不占用节点详评名额，不另做选股排序。'}</div></section>`;
}
function transitionMarkup(x){return `<div class="direction-transition"><span class="direction-tag ${x.from}">${x.fromLabel}</span><span class="transition-arrow">→</span><span class="direction-tag ${x.to}">${x.toLabel}</span><small>短期判断</small></div>`}
function opinionUpdates(){
 const changes=R.directionUpdates(DATA);
 return `<section class="panel changes-panel"><div class="panel-head"><h2 class="panel-heading">观点更新 <span class="change-total">${changes.length}</span></h2><button class="small-link" data-action="all-updates">全部 ${icon('arrow-up-right')}</button></div><p class="changes-caption">未来 1—3 日的方向判断发生切换</p><div class="updates-scroll-shell"><div class="change-list" id="opinionViewport" tabindex="0" role="region" aria-label="上下滚动查看全部观点更新">${changes.length?changes.map(x=>`<button class="change-item" data-update-key="${C.key(x.s)}" data-open="${C.key(x.s)}"><div class="change-title"><span class="change-name">${escape(x.s.name)}</span>${viewPill(x.r)}</div>${transitionMarkup(x)}<p>${escape(x.reason||'原报告未填写方向变化原因。')}</p><div class="update-meta"><span>${dateWord(x.s).w} ${dateWord(x.s).d.slice(5).replace('-','.')} · 第 ${x.r.day} 天</span><span>${x.previous.date.slice(5).replace('-','.')} → ${x.r.date.slice(5).replace('-','.')}</span></div></button>`).join(''):`<div class="empty">${icon('check')}<h3>本日没有方向切换</h3><p>不把“同方向内信心增强或减弱”当作方向变化，也不为首次复盘补写上一观点。</p></div>`}</div><div id="updatesScrollbar" class="updates-scrollbar" role="scrollbar" aria-label="上下滚动观点更新" aria-controls="opinionViewport" aria-orientation="vertical" aria-valuemin="0" aria-valuemax="0" aria-valuenow="0" tabindex="0"><span></span></div></div><div class="updates-foot"><span>${changes.length>3?'向下滚动，查看其余更新':'已显示本日全部更新'}</span><button class="text-button" data-action="direction-info">变化口径 ${icon('info')}</button></div></section>`;
}
function overview(){
 // 首页轨道只保留判断仍成立的记录；失效记录不删，仍可从“全部观察”查看。
 const all=R.recommendations(DATA),cards=all.filter(s=>!R.isInvalid(s,DATA)),hidden=all.length-cards.length;
 return `<div class="page-enter">${intro('AFTER THE CLOSE / BEFORE THE NEXT MOVE','收盘之后，<span class="intro-accent">看清变化。</span>','先看市场，再看需要深读的股票，以及真正改变的判断。')}${marketSection()}<div class="overview-grid">${deepFocus()}${opinionUpdates()}</div><div class="section-heading"><h2>推荐股票清单 <small>RECOMMENDATION RECORDS</small></h2><div class="section-actions"><button class="small-link" data-action="all-recommendations">全部 ${all.length} 条 ${icon('arrow-right')}</button></div></div><div class="rail-description">按推荐日期由近到远 · 同一股票的不同推荐分别保留${hidden?` · 已隐藏 ${hidden} 条判断失效记录`:''}</div><div class="observation-cards recommendation-rail" id="recommendationRail" tabindex="0" role="region" aria-label="左右滚动推荐股票清单">${cards.length?cards.map(card).join(''):'<div class="empty"><h3>暂无推荐记录</h3><p>市场信息仍可查看，不填入示例股票。</p></div>'}</div><div class="rail-controls"><button class="icon-btn" data-rail-step="-1" aria-label="向左滚动推荐股票">${icon('chevron-left')}</button><input type="range" class="rail-scrollbar" id="railScrollbar" min="0" max="100" step="1" value="0" aria-label="左右滚动全部推荐股票"><button class="icon-btn" data-rail-step="1" aria-label="向右滚动推荐股票">${icon('chevron-right')}</button><span id="railPosition" class="mono"></span></div><div class="overview-note">${icon('orbit')}<span><b>换个角度看全局。</b> 在观察星图中，比较每条记录的观察进度与价格表现。</span><button data-nav="map">探索观察星图 ↗</button></div></div>`;
}
function filteredStocks(){
 let list=R.filterRecords(DATA,state.filters).filter(s=>state.page!=='favorites'||state.favorites.has(C.key(s)));
 const q=state.query.trim().toLowerCase();if(q)list=list.filter(s=>`${s.name} ${s.code} ${s.recDate} ${s.formedOn||''}`.toLowerCase().includes(q));
 return list.sort((a,b)=>{
  if(['return','close'].includes(state.sort)){const val=s=>state.sort==='close'?R.closeOnDate(s,DATA):R.returnOnDate(s,DATA),av=val(a),bv=val(b);if(av===null&&bv===null)return 0;if(av===null)return 1;if(bv===null)return -1;return (av-bv)*state.direction;}
  if(state.sort==='days')return(a.days-b.days)*state.direction;
  return a.recDate.localeCompare(b.recDate)*state.direction;
 });
}
function tableRows(){return filteredStocks().map(s=>{
 const ret=R.returnOnDate(s,DATA),close=R.closeOnDate(s,DATA),r=R.latest(s,DATA),invalid=R.isInvalid(s,DATA);
 return `<tr data-open="${C.key(s)}" data-invalid="${invalid}" tabindex="0" role="button" aria-label="打开${escape(s.name)} ${dateWord(s).d}的复盘"><td><div class="table-stock"><div><strong>${escape(s.name)}</strong><small>${s.code}</small></div></div></td><td><span class="mono secondary">${dateWord(s).d.replaceAll('-','.')}</span></td><td>${progress(s)}<div class="table-progress"><i style="width:${Math.min(s.days/OBS.days,1)*100}%"></i></div></td><td><b class="num ${signedClass(ret)}">${pct(ret)}</b></td><td class="daily-close"><span class="num">${money(close)}</span>${close===null?`<small>${s.suspended?'当日停牌':'当日无行情'}</small>`:''}</td><td>${ledgerPill(s)}<small class="review-date-note">${r?`${r.date.slice(5).replace('-','.')} 复盘`:invalid?'沿用原记录失效状态':'未保存复盘'}</small></td><td><div style="display:flex;align-items:center;gap:10px">${star(s)}${icon('chevron-right')}</div></td></tr>`;
}).join('')}
function scopeDescription(){
 const f=state.filters,n=stocks.filter(s=>R.isInvalid(s,DATA)).length;
 const main=({default:`默认显示全部未失效记录 · 已隐藏 ${n} 条失效记录`,active:`全部（不含失效） · 已隐藏 ${n} 条失效记录`,invalid:'仅显示判断失效的记录',both:'全部 + 判断失效 · 包含所有推荐记录'})[f.scope];
 return main+(f.positive?' · 高于参考价':'')+(f.opinion!=='any'?` · ${R.OPINION_OPTIONS.find(x=>x.value===f.opinion)?.label}`:'');
}
function records(){
 const fav=state.page==='favorites',f=state.filters,allOn=['active','both'].includes(f.scope),invalidOn=['invalid','both'].includes(f.scope);
 return `<div class="page-enter">${intro(fav?'SAVED OBSERVATIONS':'EVERY THESIS / EVERY RECORD',fav?'留给自己，多看一眼。':'每一条判断，都留下记录。',fav?'收藏保存在当前浏览器，只是阅读清单，不是持仓。':'同一股票的不同推荐分别保留；价格表现不等于判断仍然成立。',`<button class="quiet-btn" data-action="export">${icon('download')}导出快照</button>`)}<div class="toolbar records-toolbar"><div class="filter-tabs" aria-label="筛选观察记录"><button class="filter-tab ${allOn?'active':''} ${f.scope==='default'?'default-scope':''}" data-filter="all" aria-pressed="${allOn}">${allOn?icon('check'):''}全部</button><button class="filter-tab ${f.positive?'active':''}" data-filter="positive" aria-pressed="${f.positive}">${f.positive?icon('check'):''}高于参考价</button><label class="opinion-filter">复盘观点<select id="opinionFilter" class="select-input" aria-label="选择复盘观点">${R.OPINION_OPTIONS.map(x=>`<option value="${x.value}" ${f.opinion===x.value?'selected':''}>${x.label}</option>`).join('')}</select></label><span class="filter-separator"></span><button class="filter-tab invalid-filter ${invalidOn?'active':''}" data-filter="invalid" aria-pressed="${invalidOn}">${invalidOn?icon('check'):''}判断失效</button>${f.scope==='both'?'<button class="text-button only-invalid" data-filter="only-invalid">仅看失效</button>':''}</div><div class="toolbar-right"><label class="inline-search">${icon('search')}<input id="recordSearch" placeholder="名称、代码、推荐日期" aria-label="筛选股票" value="${escape(state.query)}"></label></div></div><div class="filter-summary"><span id="filterSummary">${scopeDescription()}</span><button class="text-button" data-action="filter-info">如何组合筛选 ${icon('info')}</button></div><section class="panel"><div class="table-wrap"><table class="records-table"><thead><tr><th>股票 / 代码</th><th><button data-sort="date">推荐日期 ${state.sort==='date'?(state.direction<0?'↓':'↑'):'↕'}</button></th><th><button data-sort="days">观察进度 ${state.sort==='days'?(state.direction<0?'↓':'↑'):'↕'}</button></th><th><button data-sort="return">较参考价涨跌 ${state.sort==='return'?(state.direction<0?'↓':'↑'):'↕'}</button></th><th><button data-sort="close">当日收盘价 ${state.sort==='close'?(state.direction<0?'↓':'↑'):'↕'}</button><small>${DATA.analysis_date.slice(5).replace('-','.')} · 元</small></th><th>复盘观点</th><th></th></tr></thead><tbody id="tableRows">${tableRows()}</tbody></table></div><div class="empty" id="tableEmpty" ${filteredStocks().length?'hidden':''}>${icon(fav?'star':'search')}<h3>${fav&&!state.favorites.size?'还没有收藏记录':'没有匹配的观察记录'}</h3><p>调整筛选或搜索词；缺失内容不以假数据补齐。</p><button class="quiet-btn" data-filter="reset">重置筛选 ${icon('arrow-right')}</button></div><div class="table-bottom"><span id="tableCount">${filteredStocks().length} 条记录</span><span>收盘价对应 ${DATA.analysis_date} · 不用停牌前价格冒充当日价格</span></div></section></div>`;
}
function mapSelection(s){if(!s)return '<div class="empty"><h3>暂无可展示记录</h3></div>';const m=C.metrics(s,LAST),r=C.reviewAt(s,LAST,DATA),eq=C.quoteOnIndex(s,LAST);return `<span class="eyebrow">SELECTED OBSERVATION</span><div class="stock-title"><div><h2>${escape(s.name)}</h2><small>${s.code}</small></div></div><div class="big-return ${signedClass(m.ret)}">${pct(m.ret)}</div><span class="source-hint">收盘较原参考价</span><dl><div><dt>观察进度</dt><dd>${progress(s)}</dd></div><div><dt>${dateWord(s).w}日期</dt><dd class="mono">${dateWord(s).d}</dd></div><div><dt>本期成交额</dt><dd class="mono">${money(eq?.c[4])} 亿</dd></div></dl>${viewPill(r,s.stage)}<p>${escape(r?.viewReason||s.reasonFull.slice(0,90)+'…')}</p><button class="primary-btn" data-open="${C.key(s)}">阅读完整复盘 ${icon('arrow-right')}</button>`}
// 星图数据：只读派生。原始 stocks、记录身份与其他页面一律不受影响。
function atlasData(){
 const groups=R.atlasGroups(DATA);
 const stock=groups.map(g=>({group:g,badge:R.atlasBadge(g),basis:R.atlasBasis(g,DATA)}));
 const record=[];
 for(const g of groups)for(const s of g.records)record.push({group:g,s,point:R.atlasRecordPoint(s,g,DATA)});
 return {groups,stock,record,range:R.atlasRange(stock.map(x=>x.basis),record.map(x=>x.point))};
}
function atlasRecordLabel(s){const sameYear=s.recDate.slice(0,4)===DATA.analysis_date.slice(0,4);return `${s.name} · ${sameYear?s.recDate.slice(5).replace('-','/'):s.recDate.replaceAll('-','/')}`}
function groupPanel(item){
 if(!item)return '<div class="empty"><h3>还没有选中的股票</h3><p>点击星图上的光点或“入选N次”徽标，这里展开这只股票的全部入选明细；悬停只作预览。</p></div>';
 const {group,badge,basis}=item,anchor=basis.anchor;
 const episodes=group.records.map((s,i)=>{
  const p=R.atlasRecordPoint(s,group,DATA),invalid=R.isInvalid(s,DATA);
  return `<div class="map-episode${invalid?' is-invalid':''}"><div class="map-episode-head"><b class="mono">${dateWord(s).d.replaceAll('-','.')}${group.records.length>1&&i===group.records.length-1?' <span class="muted">最新</span>':''}</b><span class="map-episode-type">${s.refKind==='event'?'事件条件':'正式推荐'}</span><b class="num ${signedClass(p.ret)}">${pct(p.ret)}</b></div><dl><div><dt>该次原参考价</dt><dd class="mono">${money(s.ref)}</dd></div><div><dt>观察进度</dt><dd>${progress(s)}</dd></div><div><dt>这一轮复盘观点</dt><dd>${ledgerPill(s)}</dd></div></dl><button class="small-link" data-open="${C.key(s)}">查看这次复盘 ${icon('arrow-right')}</button></div>`}).join('');
 const latest=group.records.length>1?group.records.at(-1):null;
 const latestPoint=latest?R.atlasRecordPoint(latest,group,DATA):null;
 return `<span class="eyebrow">SELECTED STOCK</span><div class="stock-title"><div><h2>${escape(group.name)}</h2><small>${group.code} · ${group.records[0].recDate.slice(5).replace('-','.')} — ${group.records.at(-1).recDate.slice(5).replace('-','.')} 入选</small></div></div>${badge?`<div class="map-count-badge">${icon('layers')}${escape(badge.full)}</div>`:''}<div class="big-return ${signedClass(basis.ret)}">${pct(basis.ret)}</div><span class="source-hint">${R.ATLAS_BASIS_LABEL}基准收益（最早入选 ${anchor.recDate.replaceAll('-','.')}）</span>${basis.plottable?`<dl><div><dt>${R.ATLAS_BASIS_LABEL}原参考价</dt><dd class="mono">¥ ${money(anchor.ref)}</dd></div><div><dt>报告日收盘</dt><dd class="mono">¥ ${money(basis.close)} <span class="muted">${DATA.analysis_date}</span></dd></div><div><dt>距最早入选</dt><dd>第 ${basis.day} 个交易日</dd></div></dl>`:`<p class="map-basis-missing">最早基准无法计算：${basis.reason}。不换用最新参考价，也不按 0% 绘制；明细中仍可阅读各次记录。</p>`}${latest&&latestPoint&&latestPoint.plottable?`<div class="map-latest-block"><b>最新一次 ${latest.recDate.replaceAll('-','.')}</b>：自己的涨跌 <b class="num ${signedClass(latestPoint.ret)}">${pct(latestPoint.ret)}</b>（第 ${latestPoint.day} 个交易日，较该次参考价 ${money(latest.ref)}）。单列阅读，不替换主图基准。</div>`:''}<div class="map-episodes-title">全部入选明细 · 按时间顺序</div>${episodes}<p class="map-anchor-note">主图坐标保持“${R.ATLAS_BASIS_LABEL}”口径；点开各次复盘仍按那一次的参考价、日期与观点。</p>`;
}
function mapPanelContent(){
 const a=atlasData();
 if(state.mapMode==='stock')return groupPanel(a.stock.find(x=>x.group.code===(state.mapPreview??state.mapGroup)));
 const s=a.record.map(x=>x.s).find(x=>C.key(x)===(state.mapPreview??state.mapCurrent));
 return s?mapSelection(s):'<div class="empty"><h3>还没有选中记录</h3><p>点击星图上的光点查看这一次入选的详情；每个点使用自己那次的日期与参考价。</p></div>';
}
function updateMapPanel(){const el=$('mapSelection');if(el)el.innerHTML=mapPanelContent()}
function updateMapMeta(a){
 const stockView=state.mapMode==='stock',stats=$('mapStats'),pending=$('mapPending');
 if(stats){
  const M=stocks.length,Z=stockView?a.stock.filter(x=>x.basis.plottable).length:a.record.filter(x=>x.point.plottable).length,T=stockView?a.stock.length:a.record.length,K=T-Z;
  stats.textContent=stockView?`${a.stock.length}只股票 · ${M}条入选记录 · ${Z}只有坐标 · ${K}只暂未绘制`:`${a.groups.length}只股票 · ${M}条入选记录 · ${Z}条有坐标 · ${K}条暂未绘制`;
 }
 if(pending){
  const rows=stockView?a.stock.filter(x=>!x.basis.plottable).map(item=>`<button class="map-pending-item" data-map-group="${item.group.code}"><b>${escape(item.group.name)}</b><span>${item.group.code} · 最早入选：${item.basis.reason}</span></button>`).join('')
   :a.record.filter(x=>!x.point.plottable).map(x=>`<button class="map-pending-item" data-map-id="${C.key(x.s)}"><b>${escape(x.s.name)}</b><span>${x.s.recDate.replaceAll('-','.')} · ${x.point.reason}</span></button>`).join('');
  pending.innerHTML=rows?`<div class="map-pending"><span class="map-pending-title">暂未绘制 · 点击查看原因与明细</span><div class="map-pending-list">${rows}</div></div>`:'';
 }
}
function mapPage(){
 const stockView=state.mapMode==='stock';
 return `<div class="page-enter">${intro('THE OBSERVATION ATLAS','每一只股票，一条观察主线。','同股多次入选合并展示；坐标按本报告最早一次入选计算，各次复盘分别保留。')}
 <div class="map-toolbar"><div class="segmented" aria-label="星图视图切换">${[['stock','按股票看'],['record','按每次入选看']].map(([m,l])=>`<button data-map-mode="${m}" class="${state.mapMode===m?'active':''}" aria-pressed="${state.mapMode===m}">${l}</button>`).join('')}</div><span class="map-stats" id="mapStats"></span></div>
 <div class="map-layout"><section class="panel map-panel"><div class="panel-head"><h2 class="panel-heading">${icon('orbit')}观察星图 <small>PERFORMANCE × TIME</small></h2><span class="source-hint">${stockView?'股票视角 · 一股一点':'记录视角 · 一次一点'}</span></div><div class="map-wrap"><svg id="atlas" class="chart" role="img" aria-label="观察星图散点图：横向为入选后的交易日数，纵向为较参考价涨跌"></svg></div><div id="mapPending"></div><div class="graph-key"><span class="chip-dot"></span>高于参考价 <span class="chip-dot down"></span>低于参考价 <span style="margin-left:8px">圆点大小＝当日成交额（压缩比例）</span></div><p class="map-note">${stockView?'坐标基于本报告最早一次入选，不是历史首次声明；各次复盘分别保留，不延长任何一次 20 天观察窗口。悬停预览，点击固定选中。':'按每次入选分别计算：每个点使用自己那次的日期与参考价，配同一报告日的真实行情。两个点是不同基准，不连成价格轨迹。'}</p></section><aside class="panel map-selection" id="mapSelection">${mapPanelContent()}</aside></div></div>`}
function journal(){
 const d={...DATA,analysis_date:state.journalDate},updates=R.directionUpdates(d),byKey=new Map(updates.map(x=>[C.key(x.s),x]));
 const entries=state.journalMode==='directions'?updates:stocks.flatMap(s=>s.reviews.filter(r=>r.date===state.journalDate&&(state.journalMode==='all'||r.viewChanged)).map(r=>({s,r})));
 const labels=[['directions','方向更新'],['changes','全部观点调整'],['all','当日全部复盘']];
 return `<div class="page-enter">${intro('A JOURNAL OF CHANGING MINDS','好的复盘，也记录改变。','方向更新比较相邻两次复盘的短期判断；它不等于当天涨跌，也不等于信心标签改变。',`<div class="segmented journal-modes">${labels.map(([id,label])=>`<button data-journal-mode="${id}" class="${state.journalMode===id?'active':''}">${label}</button>`).join('')}</div>`)}<div class="journal-layout"><aside class="journal-side"><h2>${state.journalDate.slice(-2)}<span class="muted" style="font-size:26px"> / ${state.journalDate.slice(5,7)}</span></h2><p>${state.journalDate.slice(0,4)} · 复盘归属日期<br>不是报告实际生成时点</p><dl><div><dt>本日方向更新</dt><dd class="accent">${updates.length}</dd></div><div><dt>转为上涨</dt><dd>${updates.filter(x=>x.to==='up').length}</dd></div><div><dt>转为下跌</dt><dd>${updates.filter(x=>x.to==='down').length}</dd></div></dl><label class="sr-only" for="journalDate">复盘日期</label><select class="select-input" id="journalDate">${DATA.review_dates.map(date=>`<option value="${date}" ${date===state.journalDate?'selected':''}>${date.replaceAll('-',' / ')}</option>`).join('')}</select></aside><div class="journal-feed">${entries.length?entries.map(({s,r})=>{const index=C.indexOfDate(DATA,r.date),m=C.metrics(s,index),x=byKey.get(C.key(s));return `<article class="journal-entry ${tone(r)}"><div class="panel"><div class="entry-top"><h3>${escape(s.name)}<small class="journal-code">${s.code} · ${dateWord(s).d} ${dateWord(s).w}</small></h3>${viewPill(r)}</div>${x?transitionMarkup(x):''}<p>${escape(state.journalMode==='directions'?(r.outlookReason||r.viewReason):(r.viewReason||r.summary_copy))}</p>${x?`<div class="transition-detail"><span>${x.previous.date}：${escape(x.previous.base)}</span><span>${r.date}：${escape(r.base)}</span></div><p class="journal-reason">相比上次：${escape(r.viewReason||'未保存比较原因')}</p>`:''}<div class="entry-foot"><span>第 ${r.day} 天 <span style="margin:0 8px">·</span>${kindLabel(r)} <span style="margin:0 8px">·</span><span class="${signedClass(m.ret)}">${pct(m.ret)}</span> 较参考价</span><button class="small-link" data-open="${C.key(s)}" data-open-end="${index}">回到这一天 ${icon('arrow-up-right')}</button></div></div></article>`}).join(''):`<div class="empty">${icon('history')}<h3>这一天没有${state.journalMode==='directions'?'方向更新':state.journalMode==='changes'?'观点调整':'复盘记录'}</h3><p>不将首次复盘或无法识别的方向计为变化。</p></div>`}</div></div></div>`;
}
function detail(){
 const s=byId(state.current),end=state.end,m=C.metrics(s,end),q=C.lastAvailableQuote(s,end),eq=C.quoteOnIndex(s,end),r=C.reviewAt(s,end,DATA),days=C.daysAt(s,end),isLatest=end===LAST;
 const closeSub=eq?`${DATA.dates[eq.i]} · 当日 ${pct(C.dayChange(s,eq.i))}`:q?`本日无有效报价；最近有效报价 ${DATA.dates[q.i]}`:'没有有效报价';
 const prevBar=end>0?s.candles[end-1]:null,prevAmt=prevBar&&C.valid(prevBar[4])?prevBar[4]:null;
 const amtSub=prevAmt===null?'前一交易日无成交额数据':(eq&&C.valid(eq.c[4])?`较前一日 ${pct((eq.c[4]/prevAmt-1)*100)}`:'当日缺成交额');
 const volSub=m.volToday===null?'当日缺成交额':(m.volN?`前${m.volN}日均 ${money(m.volBase)} 亿`:'前5日无有效成交额');
 const fields=[['收盘价',eq?'¥ '+money(eq.c[3]):'—','',closeSub],['较参考价涨跌',pct(m.ret),signedClass(m.ret),s.ref?`原参考价 ¥ ${money(s.ref)}`:'暂无可靠推荐参考价'],['当日成交额',eq&&C.valid(eq.c[4])?`${money(eq.c[4])} 亿`:'—','',amtSub],['量能较5日均量',pct(m.volDelta),signedClass(m.volDelta),volSub],['现价仍需上涨',pct(m.remaining),'',s.ref?`至${Math.round(OBS.target*100)}%观察目标 ¥ ${money(targetPrice(s))}`:'目标尚不能计算']];
 const confirmLabel='支持这次走势判断的表现',riskLabel='会改变这次走势判断的表现';
 const events=s.reviews.filter(rv=>rv.date<=C.dateAt(end,DATA)).slice().reverse();
 return `<div class="page-enter"><button class="back-button" data-action="back">${icon('arrow-left')}返回观察清单</button><section class="detail-heading"><div class="stock-title"><div><h1>${escape(s.name)}</h1><small>${s.code} &nbsp; / &nbsp; ${escape(s.industryName)} &nbsp; / &nbsp; ${dateWord(s).d.replaceAll('-','.')} ${dateWord(s).w}${s.d0?` · 首日观察 ${s.recDate.replaceAll('-','.')}`:''}</small></div></div><div class="detail-actions">${star(s)}<button class="quiet-btn" data-action="export-record">${icon('download')}导出记录</button><button class="primary-btn" data-action="play" ${s.d0||s.days<1?'disabled':''}>${icon(state.playing?'pause':'play')}<span>${state.playing?'暂停回看':'回放观察过程'}</span></button></div></section>
 <div class="detail-metrics">${fields.map(([label,val,cls,sub])=>`<div class="detail-metric"><div class="label">${label}</div><strong class="num ${cls}">${val}</strong><small>${sub}</small></div>`).join('')}</div>
 <div class="detail-grid"><section class="panel"><div class="detail-chart-head"><h2>价格与成交<span>${C.dateAt(end,DATA).replaceAll('-','.')} / ${s.d0?'待首日观察':`第 ${days} 天`}</span></h2><div class="segmented" aria-label="图表类型">${[['line','收盘走势'],['candle','K 线'],['relative','相对表现']].map(([mode,label])=>`<button class="${state.chartMode===mode?'active':''}" data-chart-mode="${mode}" ${mode==='relative'&&(s.d0||s.ref===null)?'disabled':''}>${label}</button>`).join('')}</div></div><div class="detail-chart-wrap">${plot(s,end,state.chartMode)}</div><div class="chart-subnote">${state.chartMode==='relative'?`<span>首个观察日收盘＝100；与参考价收益口径不同。</span><span class="mini-legend"><span><i class="legend-line"></i>个股</span><span><i class="legend-line" style="background:var(--blue)"></i>${escape(s.industryName)}</span><span><i class="legend-line" style="background:var(--amber)"></i>${escape(DATA.market_name)}</span></span>`:`<span>${state.chartMode==='candle'?'红K：收盘≥开盘 · 绿K：收盘&lt;开盘':'实线：收盘'} &nbsp; 蓝虚线：参考价 &nbsp; 金虚线：${Math.round(OBS.target*100)}%观察目标</span><span>下方为成交额，单位：亿元</span>`}${!isLatest?'<span class="accent">正在回看：之后的走势与复盘已隐藏</span>':''}</div><div class="timeline-control"><div class="timeline-top"><span>${s.d0?'首个观察日尚未到达':`正在观察 <b>第 ${days} 天</b> / ${OBS.days} 个交易日`}</span><button class="small-link" data-action="latest" ${isLatest?'disabled':''}>回到最新 ${icon('arrow-right')}</button></div><div class="day-ruler" aria-label="选择观察交易日">${Array.from({length:rulerLength(s)},(_,i)=>{const day=i+1,idx=s.recIndex+i,observed=!s.d0&&day<=s.days&&idx<=LAST,changed=s.reviews.some(rv=>rv.day===day&&rv.viewChanged),extended=day>OBS.days;return `<button class="day-dot ${observed?'observed':''} ${day===days?'active':''} ${changed?'changed':''}" data-day="${day}" ${observed?'':'disabled'} title="${observed?`第${day}天 · ${extended?'后续观察 · ':''}${DATA.dates[idx]}`:`第${day}天尚未观察`}" aria-label="第${day}天${extended?'（后续观察）':''}${observed?'':'尚未观察'}" aria-pressed="${day===days}">${day.toString().padStart(2,'0')}</button>`}).join('')}</div><div class="timeline-labels"><span>第一天</span><span>小金点＝观点发生变化</span><span>第${OBS.days}天${s.days>OBS.days?' · 之后为既有后续观察':''}</span></div>${s.d0?'':`<input class="replay-range" id="replayRange" type="range" min="1" max="${Math.max(1,s.days)}" value="${Math.max(1,days)}" aria-label="拖动回看第几个交易日">`}</div></section>
 <aside class="panel opinion-panel"><span class="eyebrow">REVIEW / 原报告观点 <span>${r?r.date.slice(5).replace('-','.'):'—'}</span></span>${viewPill(r,s.d0?'待首日观察':'没有复盘记录')}<h3>${escape(baseLabel(r))}</h3><p>${escape(r?.outlookReason||(s.d0?'这条记录计划从下一交易日开始观察。现在只能阅读原推荐理由，不能计算推荐后涨跌。':'该条记录未附复盘正文；行情可以查看，但不能用价格自动补出研究结论。'))}</p><div class="opinion-separator"></div><div class="opinion-row"><label>${icon('check')}${confirmLabel}</label><p>${escape(r?.confirm||'原报告本次未填写')}</p></div><div class="opinion-row"><label>${icon('flag')}${riskLabel}</label><p>${escape(r?.risk||'原报告本次未填写')}</p></div><div class="pill-note">${isLatest?`原数据阶段：${escape(s.stage)} · 与研究观点分开保留`:'回看中的阶段仅依据所选日期前的复盘，不套用最新快照阶段。'}${r&&r.date!==C.dateAt(end,DATA)?`<br>${stoppedTracking(s)?`已停止主动跟踪${s.trackingExitDate?`（${dotDate(s.trackingExitDate)}起）`:''}，此后无每日复盘；右栏为停止前最近的 ${r.date} 原记录。`:`所选日没有新复盘，显示最近的 ${r.date} 原记录。`}`:''}</div><button class="small-link" data-action="read-full">阅读原始判断 ${icon('arrow-right')}</button></aside></div>
 <div class="detail-bottom"><section class="panel" id="reviewPanel"><div class="review-tabs" aria-label="阅读内容"><button class="review-tab ${state.reviewTab==='latest'?'active':''}" data-review-tab="latest">这一天的复盘</button><button class="review-tab ${state.reviewTab==='original'?'active':''}" data-review-tab="original">当初为什么选它</button><button class="review-tab ${state.reviewTab==='company'?'active':''}" data-review-tab="company">公司资料</button></div><div class="review-body">${reviewBody(s,r,end)}</div></section><aside class="panel event-panel"><h3>一路走来的判断</h3><div class="event-list">${events.map(rv=>`<div class="event-item ${rv.viewChanged?'changed':''} ${rv.date===r?.date?'active':''}" data-day="${rv.day}" role="button" tabindex="0"><time>${rv.date.slice(5).replace('-','.')} · 第${rv.day}天 · ${kindLabel(rv)}</time><b>${escape(rv.viewLabel||kindLabel(rv))}</b><p>${escape(rv.viewReason||rv.headline)}</p></div>`).join('')}<div class="event-item" data-review-tab="original" role="button" tabindex="0"><time>${dateWord(s).d.slice(5).replace('-','.')} · ${s.d0?'计划推荐日':'原推荐日'}</time><b>从这个判断开始</b><p>${escape(s.reasonFull)}</p></div></div><p class="source-hint" style="margin-top:23px">只展示当前回看日及之前的记录。<br>全文观点来自原报告，未由DEMO重写。</p></aside></div></div>`;
}
const introStamp=t=>{const s=String(t||'');return /^\d{4}-\d{2}-\d{2}T/.test(s)?s.slice(0,16).replace('T',' '):s};
const safeHref=u=>typeof u==='string'&&/^https?:\/\//i.test(u)?u:null;
function introTable(tbl){
 if(!tbl||!Array.isArray(tbl.columns)||!Array.isArray(tbl.rows))return '';
 const head=tbl.columns.map(c=>'<th>'+escape(c)+'</th>').join('');
 const body=tbl.rows.map(r=>'<tr>'+r.map(c=>'<td>'+escape(c)+'</td>').join('')+'</tr>').join('');
 const note=tbl.note?'<p class="intro-table-note">'+escape(tbl.note)+'</p>':'';
 return `<div class="intro-table-wrap"><table class="intro-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${note}`;
}
function companyTabBody(s){
 const intro=s.companyIntroduction;
 if(intro&&Array.isArray(intro.sections)&&intro.sections.length){
  const cut=introStamp(intro.as_of);
  const gen=introStamp(intro.generated_at);
  const secs=intro.sections.map(sec=>{
   const paras=(sec.paragraphs||[]).map(p=>'<p>'+escape(p)+'</p>').join('');
   const refs=(sec.source_ids||[]).length?`<span class="intro-refs">${sec.source_ids.map(id=>'['+escape(id)+']').join(' ')}</span>`:'';
   return `<section class="intro-section"><h4>${escape(sec.title)}${refs}</h4>${paras}${introTable(sec.table)}</section>`;
  }).join('');
  const sources=(intro.sources||[]).map(src=>{
   const href=safeHref(src.url);
   const link=href?` <a href="${escape(href)}" target="_blank" rel="noopener noreferrer">原文</a>`:'';
   const meta=src.kind==='warehouse'
     ?`本地事实仓 · ${escape(src.dataset||'')}${src.report_period?' · 报告期 '+escape(src.report_period):''}`
     :`官方文件 · 公开依据：${escape(src.availability_basis||'')}${src.retrieved_at?' · 实际补读 '+escape(introStamp(src.retrieved_at)):''}`;
   return `<li><b>${escape(src.id)}</b> ${escape(src.title||'')}<span class="intro-src-meta">${meta} · 可用 ${escape(introStamp(src.available_at))}${src.locator?' · '+escape(src.locator):''}</span>${link}</li>`;
  }).join('');
  const lims=(intro.limitations||[]).length?`<div class="intro-limit"><h4>资料限制</h4><ul>${intro.limitations.map(l=>'<li>'+escape(l)+'</li>').join('')}</ul></div>`:'';
  const back=introStamp(intro.as_of)!==gen?`，实际编写于 ${escape(gen)}`:'';
  return `<div class="review-meta"><span>COMPANY PROFILE · 推荐时点资料</span><span>资料截至 ${escape(cut)}</span></div><h3>${escape(s.name)}</h3><div class="intro-body">${secs}${lims}${sources.length?`<details class="intro-sources"><summary>资料来源（${(intro.sources||[]).length}）</summary><ul>${sources}</ul></details>`:''}<p class="source-hint">本篇介绍只使用推荐研究截止（${escape(cut)}）前能取得的公开资料${back}；覆盖文中列出的来源，不表示核验了全部公告，也不构成新的买卖建议。</p></div>`;
 }
 if(s.company)return `<div class="review-meta"><span>COMPANY PROFILE</span><span>${escape(sourceLabel())}</span></div><h3>${escape(s.name)}</h3><div class="copy"><p>${escape(s.company)}</p></div><p class="source-hint">旧快照中的简要资料；完整推荐时点介绍暂缺。</p>`;
 return `<div class="review-meta"><span>COMPANY PROFILE</span><span>暂缺</span></div><h3>${escape(s.name)}</h3><div class="copy"><p>这次推荐的完整公司介绍暂未生成。</p></div><p class="source-hint">介绍缺失是资料暂缺，不代表公司经营变化。</p>`;
}
function reviewBody(s,r,end){
 if(state.reviewTab==='original')return `<div class="review-meta"><span>ORIGINAL THESIS</span><span>${dateWord(s).d} · ${escape(s.refKind==='event'?'事件条件记录':'原推荐记录')}</span></div><h3>当时看中的是什么，<br>最担心的又是什么。</h3><div class="copy"><p>${escape(s.reasonFull)}</p></div><div class="original-risk"><h4>原推荐中写下的风险</h4><p>${escape(s.reasonRisk||'原记录未附风险文字。')}</p></div><p class="source-hint">以上为原报告文本。时间轴变化不会改写最初的推荐理由。</p>`;
 if(state.reviewTab==='company')return companyTabBody(s);
 if(!r)return `<div class="empty">${icon('book')}<h3>${s.d0?'第一天的故事，还没开始。':'这一天还没有复盘文字。'}</h3><p>${s.d0?'价格图只展示首日观察前的历史走势。':'仅保留源数据已有的价格，不以走势图代写结论。'}</p><button class="quiet-btn" data-review-tab="original">看看当初为什么选择它 ${icon('arrow-right')}</button></div>`;
 const selectedDate=C.dateAt(end,DATA);
 if(r.date!==selectedDate&&stoppedTracking(s)){
  const last=lastReviewOf(s);
  return `<div class="review-meta"><span>第${C.daysAt(s,end)}天 · ${dotDate(selectedDate)}</span><span>停止跟踪 · 无当日复盘</span></div><h3>这一天没有复盘：这条记录已停止主动跟踪。</h3><div class="copy"><p>这条记录自第${last.day}天（${dotDate(last.date)}）起停止主动跟踪，之后不再生成逐日复盘；程序继续记录每天收盘，直到第20个交易日再以节点详评形成最终结论。这一天的价格与成交照常显示，但停止前的旧复盘不重复当作这一天的结论。</p>${s.trackingExitReason?`<p>停止当天写下的理由：${escape(s.trackingExitReason)}</p>`:''}</div><button class="quiet-btn" data-day="${last.day}">阅读停止前的最后一篇复盘（第${last.day}天 · ${dotDate(last.date)}）${icon('arrow-right')}</button><p class="source-hint">复盘合同：停止主动跟踪后，次日起不再生成每日复盘，也不占详评名额；历史复盘保留，不由展示层补写。</p>`;
 }
 const copy=(r.copy||r.summary_copy||'').split(/\n\s*\n/).filter(Boolean);
 if((r.review_kind==='regular_detail'||r.review_kind==='checkpoint_detail'||r.review_kind==='brief')&&copy.length>1&&copy[0]===r.headline&&r.headline.startsWith(s.name+'｜'))copy.shift();
 // 只渲染该记录（及对应当日）实际检测到的结构化数据缺口；没有核对能力就不造具体提示，
 // 保留“原文未经重新核对”的通用声明（F01：删除按股票名/日期/价格定制的特例分支）。
 const issues=(s.dataIssues||[]).filter(x=>!x.reviewDate||x.reviewDate===r.date);
 return `<div class="review-meta"><span>${r.date.replaceAll('-','.')} / 第${r.day}天</span><span>${kindLabel(r)}</span>${viewPill(r)}</div><h3>${escape(r.headline)}</h3><div class="copy">${copy.map(p=>`<p>${escape(p)}</p>`).join('')}</div>${issues.map(x=>`<div class="warning-note">${escape(x.message)}</div>`).join('')}<p class="source-hint">原报告全文保留，包含原有措辞及可能不一致的数字；页面未做原文数字核对。上方图表与指标仅由价格数组计算。${r.as_of?`<br>原记录生成截止：${escape(r.as_of)}`:''}</p>`;
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
  if(C.valid(s.ref)&&s.ref>0&&!s.d0&&end>=s.recIndex&&C.valid(targetPrice(s)))values.push(s.ref,targetPrice(s));
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
  out+=`<line x1="${rx}" x2="${W-pad.r+5}" y1="${y(targetPrice(s))}" y2="${y(targetPrice(s))}" stroke="var(--amber)" opacity=".5" stroke-width=".8" stroke-dasharray="4 5"/><text class="chart-label" x="${W-pad.r-4}" y="${y(targetPrice(s))-7}" text-anchor="end" style="fill:var(--amber);font-size:${small?8:9}px">观察目标 · ${money(targetPrice(s))}</text>`;
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
 const a=atlasData(),stockView=state.mapMode==='stock';
 updateMapMeta(a);
 const W=svg.clientWidth,H=svg.clientHeight,small=W<500,pad={l:small?46:56,r:small?22:44,t:34,b:46};
 svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
 if(!a.range){svg.innerHTML='<text x="40" y="70" class="chart-label">暂无可计算的坐标记录</text>';svg.onpointermove=null;svg.onpointerleave=null;return}
 const {lo,hi,maxDay}=a.range,plotW=W-pad.l-pad.r,plotH=H-pad.t-pad.b;
 // 轴范围来自本报告真实数据（含 0 与全部可绘制点），不再是固定 ±12%。
 const x=day=>pad.l+(maxDay>1?(day-1)/(maxDay-1):.5)*plotW,y=ret=>H-pad.b-(ret-lo)/(hi-lo)*plotH;
 let out=`<defs><radialGradient id="atlas-glow"><stop offset="0" stop-color="var(--accent)" stop-opacity=".07"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></radialGradient><pattern id="atlas-dots" width="18" height="18" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".6" fill="var(--muted)" opacity=".24"/></pattern></defs><rect x="${pad.l}" y="${pad.t}" width="${plotW}" height="${plotH}" fill="url(#atlas-dots)"/>`;
 for(let j=0;j<=4;j++){const v=lo+(hi-lo)*j/4,zero=Math.abs(v)<1e-9,yy=y(v);out+=`<line x1="${pad.l}" x2="${W-pad.r}" y1="${yy}" y2="${yy}" stroke="${zero?'var(--secondary)':'var(--border)'}" stroke-dasharray="${zero?'5 5':'2 6'}" opacity="${zero?.55:.7}"/><text x="${pad.l-9}" y="${yy+3}" text-anchor="end" style="font-size:${small?8:9}px">${v>0?'+':''}${v.toFixed(1)}%</text>`;}
 const step=maxDay>24?5:2;
 for(let d=2;d<=maxDay;d+=step){out+=`<line x1="${x(d)}" x2="${x(d)}" y1="${pad.t}" y2="${H-pad.b}" stroke="var(--border)" opacity=".45"/><text x="${x(d)}" y="${H-pad.b+20}" text-anchor="middle" style="font-size:9px">${d}</text>`;}
 // F13 模式文案：轴说明随股票/记录模式变化；股票视图=本报告最早记录，记录视图=该次入选。
 const axisY=stockView?'较最早记录参考价涨跌':'较该次入选参考价涨跌';
 const axisX=stockView?`自${R.ATLAS_BASIS_LABEL}的首个观察日起的交易日 →`:'自该次入选的首个观察日起的交易日 →';
 const axisZero=stockView?'零线＝该记录原参考价':'零线＝该次原参考价';
 out+=`<text class="chart-label" x="${pad.l}" y="16" style="font-size:9px">${axisY}</text><text class="chart-label" x="${W-pad.r}" y="${H-5}" text-anchor="end" style="font-size:9px">${axisX}</text><text x="${pad.l+10}" y="${y(0)-9}" class="chart-label" style="font-size:8px;opacity:.6">${axisZero}</text>`;
 const iLast=R.indexOfDate(DATA,DATA.analysis_date),dots=[];
 if(stockView)for(const item of a.stock){
  if(!item.basis.plottable)continue;
  const amt=item.group.records.map(s=>s.candles[iLast]?.[4]).find(C.valid);
  dots.push({id:item.group.code,attr:'data-map-group',rec:item.group.records[0],name:item.group.name,label:item.group.name,badge:item.badge?.short||null,day:item.basis.day,ret:item.basis.ret,amt:C.valid(amt)?amt:0,active:item.group.code===state.mapGroup});
 }else for(const x0 of a.record){
  const p=x0.point;if(!p.plottable)continue;
  const amt=x0.s.candles[iLast]?.[4];
  dots.push({id:C.key(x0.s),attr:'data-map-id',rec:x0.s,name:x0.s.name,label:atlasRecordLabel(x0.s),badge:null,day:p.day,ret:p.ret,amt:C.valid(amt)?amt:0,active:C.key(x0.s)===state.mapCurrent});
 }
 // 标签只贴自己的点：理想放在点上方，放不下上下各让一格（±12px），
 // 仍放不下就省略文字（点、徽标优先级与悬停提示不受影响）。
 // 徽标（多次入选）与选中点优先占位；矩形碰撞按横向+纵向同时判断。
 const placed=[],labelY=Array(dots.length).fill(null),sideR=Array(dots.length).fill(false);
 const order=dots.map((_,i)=>i).sort((i,j)=>((dots[j].badge?2:0)+(dots[j].active?1:0))-((dots[i].badge?2:0)+(dots[i].active?1:0)));
 for(const i of order){
  const d0=dots[i],xx=x(d0.day),yy=y(d0.ret),radius=d0.amt>0?Math.min(small?10:13,3+Math.sqrt(d0.amt)*1.15):3.5,fs=small?8:10;
  const w=d0.label.length*fs+(d0.badge?d0.badge.length*(fs-1)+23:0);
  const rightX=xx+radius+8,leftX=xx-radius-8-w;
  const side=rightX>=pad.l-8&&rightX+w<=W-2?true:leftX>=pad.l-8&&leftX+w<=W-2?false:null;
  if(side===null)continue;
  const x1=side?rightX:leftX;sideR[i]=side;
  for(const dy of[0,-12,12]){
   const ty=yy-8+dy;
   if(!placed.some(r=>x1<r.x2&&x1+w>r.x1&&ty-10<r.y2&&ty+2>r.y1)){placed.push({x1,x2:x1+w,y1:ty-10,y2:ty+2});labelY[i]=ty;break;}
  }
 }
 dots.forEach((d0,i)=>{
  const xx=x(d0.day),yy=y(d0.ret),radius=d0.amt>0?Math.min(small?10:13,3+Math.sqrt(d0.amt)*1.15):3.5,col=d0.ret>=0?'var(--up)':'var(--down)',fs=small?8:10;
  out+=`<g class="map-dot" ${d0.attr}="${d0.id}" tabindex="0" role="button" aria-label="${escape(d0.name)}，${d0.badge?escape(d0.badge)+'，':''}第${d0.day}个交易日，较参考价${pct(d0.ret)}"><circle cx="${xx}" cy="${yy}" r="${radius+9}" fill="${col}" opacity=".06"/><circle cx="${xx}" cy="${yy}" r="${radius+4}" fill="none" stroke="${col}" stroke-opacity="${d0.active?.55:.12}"/><circle class="bubble-core" cx="${xx}" cy="${yy}" r="${radius}" fill="${col}" fill-opacity="${d0.active?.7:.35}" stroke="${col}" stroke-opacity=".8" stroke-width=".9"/><circle cx="${xx}" cy="${yy}" r="1.5" fill="${col}"/>`;
  if(labelY[i]!=null){
   const nameW=d0.label.length*fs,anchor=sideR[i]?'start':'end',tx=sideR[i]?xx+radius+8:xx-radius-8;
   out+=`<text x="${tx}" y="${labelY[i]}" text-anchor="${anchor}" class="chart-label" style="fill:var(--secondary);font-size:${fs}px">${escape(d0.label)}</text>`;
   if(d0.badge){
    const bw=d0.badge.length*(fs-1)+16,bx=sideR[i]?tx+nameW+7:tx-nameW-7-bw,by=labelY[i]-10;
    out+=`<g class="map-badge"><rect x="${bx}" y="${by}" width="${bw}" height="14" rx="7" fill="var(--accent)" fill-opacity=".14" stroke="var(--accent)" stroke-opacity=".5"/><text x="${bx+bw/2}" y="${by+10}" text-anchor="middle" style="fill:var(--accent);font-size:${small?8:9}px">${escape(d0.badge)}</text></g>`;
   }
  }
  out+='</g>';
 });
 svg.innerHTML=out;
 svg.onpointermove=e=>{
  const dot=e.target.closest('.map-dot');if(!dot){hideTip();return}
  const id=stockView?dot.dataset.mapGroup:dot.dataset.mapId,d0=dots.find(z=>z.id===id);if(!d0)return;
  showTip(`<b>${escape(d0.name)} · ${dateWord(d0.rec).d}${stockView?` · ${R.ATLAS_BASIS_LABEL}`:''}</b><dl><div><dt>自${stockView?'最早记录':'该次入选'}首个观察日起</dt><dd>第 ${d0.day} 天</dd></div><div><dt>较参考价</dt><dd class="${signedClass(d0.ret)}">${pct(d0.ret)}</dd></div><div><dt>当日成交额</dt><dd>${d0.amt>0?`${money(d0.amt)} 亿`:'缺失，用固定小圆'}</dd></div></dl><div class="source-hint" style="margin-top:5px">点击固定选中${stockView?'这只股票':'这次观察'}</div>`,e);
  if(state.mapPreview!==id){state.mapPreview=id;updateMapPanel()}
 };
 svg.onpointerleave=()=>{hideTip();if(state.mapPreview!==null){state.mapPreview=null;updateMapPanel()}};
}
function showTip(html,e){const el=$('tooltip');el.innerHTML=html;el.style.display='block';const w=el.offsetWidth,h=el.offsetHeight;el.style.left=`${Math.max(10,Math.min(window.innerWidth-w-10,e.clientX+17))}px`;el.style.top=`${Math.max(10,Math.min(window.innerHeight-h-10,e.clientY+17))}px`}
function hideTip(){$('tooltip').style.display='none'}
function toast(msg){clearTimeout(toastTimer);$('toast').textContent=msg;$('toast').classList.add('show');toastTimer=setTimeout(()=>$('toast').classList.remove('show'),2300)}
function refreshCounts(){$('favCount').textContent=state.favorites.size;$('recordCount').textContent=stocks.length}
function draw(){document.querySelectorAll('.main-plot').forEach(drawPlot);drawAtlas()}
function setupOverviewScroll(){
 const rail=$('recommendationRail'),slider=$('railScrollbar'),viewport=$('opinionViewport');
 if(rail&&slider){
  rail.scrollLeft=state.railLeft;
  const sync=()=>{
   const max=Math.max(0,rail.scrollWidth-rail.clientWidth);slider.max=String(max);slider.value=String(rail.scrollLeft);slider.disabled=max===0;state.railLeft=rail.scrollLeft;
   const cards=[...rail.querySelectorAll('.observation-card')],visible=cards.map((c,i)=>({c,i})).filter(({c})=>c.offsetLeft+c.offsetWidth>rail.scrollLeft+3&&c.offsetLeft<rail.scrollLeft+rail.clientWidth-3);
   $('railPosition').textContent=cards.length?`${visible.length?visible[0].i+1:1}–${visible.length?visible.at(-1).i+1:cards.length} / ${cards.length}`:'0 / 0';
   slider.style.setProperty('--thumb-width',`${Math.max(30,slider.clientWidth*(rail.clientWidth/Math.max(1,rail.scrollWidth)))}px`);
   document.querySelector('[data-rail-step="-1"]').disabled=rail.scrollLeft<2;
   document.querySelector('[data-rail-step="1"]').disabled=rail.scrollLeft>=max-2;
  };
  rail.addEventListener('scroll',sync,{passive:true});sync();
 }
 if(viewport){
  const rows=[...viewport.querySelectorAll('.change-item')];
  if(rows.length){const h=rows.slice(0,3).reduce((n,r)=>n+r.getBoundingClientRect().height,0);viewport.style.height=`${Math.ceil(h)}px`;}
  const bar=$('updatesScrollbar'),thumb=bar?.firstElementChild;
  if(bar&&thumb){
   const sync=()=>{
    const max=Math.max(0,viewport.scrollHeight-viewport.clientHeight),track=bar.clientHeight;
    const h=max?Math.max(34,track*viewport.clientHeight/viewport.scrollHeight):track;
    thumb.style.height=`${h}px`;thumb.style.transform=`translateY(${max?(track-h)*viewport.scrollTop/max:0}px)`;
    bar.setAttribute('aria-valuemax',String(max));bar.setAttribute('aria-valuenow',String(Math.round(viewport.scrollTop)));
    bar.setAttribute('aria-disabled',String(max===0));bar.tabIndex=max?0:-1;
   };
   viewport.onscroll=sync;sync();
   bar.onpointerdown=e=>{
    e.preventDefault();bar.setPointerCapture(e.pointerId);bar.focus({preventScroll:true});
    const rect=bar.getBoundingClientRect(),h=thumb.getBoundingClientRect().height;
    const offset=e.target===thumb?e.clientY-thumb.getBoundingClientRect().top:h/2;
    const move=event=>{const ratio=Math.max(0,Math.min(1,(event.clientY-rect.top-offset)/Math.max(1,rect.height-h)));viewport.scrollTop=ratio*(viewport.scrollHeight-viewport.clientHeight);sync();};
    if(e.target!==thumb)move(e);bar.onpointermove=move;
    bar.onpointerup=()=>{bar.onpointermove=null;};bar.onlostpointercapture=()=>{bar.onpointermove=null;};
   };
   bar.onkeydown=e=>{
    const amounts={ArrowDown:55,ArrowUp:-55,PageDown:viewport.clientHeight,PageUp:-viewport.clientHeight,End:viewport.scrollHeight,Home:-viewport.scrollHeight};
    if(Object.hasOwn(amounts,e.key)){e.preventDefault();viewport.scrollTop+=amounts[e.key];sync();}
   };
  }
 }
}
function render(scroll=false){
 hideTip();
 const names={overview:'总览工作台',records:'全部观察',map:'观察星图',journal:'观点时间线',favorites:'我的收藏',detail:'个股复盘'};
 $('breadcrumb').textContent=names[state.page];
 document.querySelectorAll('.nav-item').forEach(b=>{const active=b.dataset.nav===state.page||(state.page==='detail'&&b.dataset.nav==='records');b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
 $('content').innerHTML=!stocks.length&&state.page!=='overview'?`<div class="page-enter">${intro('AFTER THE CLOSE / BEFORE THE NEXT MOVE','暂无观察记录。','本次快照没有观察记录，不填入示例股票，也不生成新的判断。')}<section class="panel"><div class="empty">${icon('layers')}<h3>暂无观察记录</h3><p>接入一份包含观察记录的快照后，页面会在原位置展示内容。</p></div></section></div>`:state.page==='overview'?overview():state.page==='map'?mapPage():state.page==='journal'?journal():state.page==='detail'?detail():records();
 hydrate();refreshCounts();setupOverviewScroll();draw();
 document.dispatchEvent(new CustomEvent("guanlan:render",{detail:{page:state.page}}));
 if(scroll){window.scrollTo({top:0,behavior:'instant'});$('content').focus({preventScroll:true});}
 document.title=state.page==='detail'?`${byId(state.current).name} · 观澜 · 光场 PRISM`:'观澜 · 光场 PRISM — 收盘之后，看清变化';
}
function stopPlayback(){if(playback)clearInterval(playback);playback=null;state.playing=false}
let returnPage='overview';
function navigate(page){stopPlayback();if(page!==state.page){state.filters=R.defaultFilters();if(page==='favorites')state.filters.scope='both';state.query=''}state.page=page;render(true)}
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
 const data=single?{...s,days:C.daysAt(s,state.end),...(state.end<LAST?{stage:null,stageType:null,attention:null,trigger:null,suspended:null}:{}),candles:s.candles.slice(0,state.end+1),industry:s.industry.slice(0,state.end+1),reviews:s.reviews.filter(r=>r.date<=date),events:s.events.filter(e=>{const iso=eventISO(e);return iso!==null&&iso<=date})}:DATA;
 // 来源由生成器提供的 sourceInfo 决定；未知来源如实写未知，保留“未经外部核验”的真实边界。
 const src=DATA.sourceInfo||{};
 const sourceNote=`${src.label||'来源未知'}${src.externallyVerified===true?'':'，未经外部核验'}`;
 const payload={demo:'观澜 · 光场 PRISM',source:sourceNote,analysis_date:DATA.analysis_date,as_of:DATA.as_of||null,price_through:date,...(single?{record:data}:{snapshot:data})};
 const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=url;a.download=single?`guanlan-${s.code}-${s.recDate}-through-${date}.json`:`guanlan-snapshot-${date}.json`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(single?'已导出所选时点的观察记录':'已导出完整快照');
}
function closeDialogs(){document.querySelectorAll('dialog[open]').forEach(d=>d.close());document.body.classList.remove('modal-open')}
// 无关键词时最多给出 8 条建议（建议范围，不是搜索结果上限）；
// 有关键词时完整结果全部进入现有滚动弹窗，不做条数截断（F06）。
const SEARCH_SUGGESTIONS=8;
function searchResults(){
 const q=$('commandInput').value.trim().toLowerCase();
 let matched=stocks.filter(s=>!q||`${s.name} ${s.code} ${s.industryName} ${s.recDate} ${s.formedOn||''}`.toLowerCase().includes(q));
 state.searchList=q?matched:matched.slice(0,SEARCH_SUGGESTIONS);
 state.searchIndex=Math.max(0,Math.min(state.searchIndex,state.searchList.length-1));
 $('searchResults').innerHTML=state.searchList.length?state.searchList.map((s,i)=>{const m=C.metrics(s,LAST);return `<button class="search-result ${i===state.searchIndex?'active':''}" data-open="${C.key(s)}"><span class="search-info"><strong>${escape(s.name)}</strong><small>${s.code} · ${dateWord(s).d} ${dateWord(s).w} · ${escape(s.industryName)}</small></span><span class="num ${signedClass(m.ret)}">${pct(m.ret)}</span>${icon('arrow-up-right')}</button>`}).join(''):`<div class="empty"><h3>没有找到匹配记录</h3><p>试试股票名称、六位代码或行业名称。</p></div>`;
}
function openSearch(){stopPlayback();$('commandInput').value='';state.searchIndex=0;searchResults();$('searchDialog').showModal();document.body.classList.add('modal-open');$('commandInput').focus()}
function openInfo(){$('infoDialog').showModal();document.body.classList.add('modal-open')}
function changeTheme(){document.body.classList.toggle('light');writeStore('guanlan.theme',document.body.classList.contains('light')?'light':'dark');draw()}
// The file deliberately uses event delegation: every visible action has one local handler.
document.addEventListener('click',e=>{
 const el=e.target.closest('button,[data-open],[data-day],[data-review-tab],[data-map-mode],[data-map-group],[data-map-id]');if(!el||el.disabled)return;
 if(el.dataset.star){e.stopPropagation();toggleStar(el.dataset.star);return}
 // 星图命中必须在通用 [data-open] 之前分流：股票视图的点不再直接打开首次详情。
 if(el.dataset.mapMode){state.mapMode=el.dataset.mapMode;state.mapPreview=null;render(false);return}
 if(el.dataset.mapGroup){state.mapMode='stock';state.mapGroup=el.dataset.mapGroup;state.mapPreview=null;updateMapPanel();drawAtlas();return}
 if(el.dataset.mapId){state.mapMode='record';state.mapCurrent=el.dataset.mapId;state.mapPreview=null;updateMapPanel();drawAtlas();return}
 if(el.dataset.open){openStock(el.dataset.open,el.dataset.openEnd?Number(el.dataset.openEnd):LAST);return}
 if(el.dataset.nav){navigate(el.dataset.nav);return}
 if(el.dataset.heroStep&&deepGroups.length){state.hero=(state.hero+Number(el.dataset.heroStep)+deepGroups.length)%deepGroups.length;state.heroRecord=0;render(false);return}
 if(el.dataset.railStep){const rail=$('recommendationRail');rail.scrollBy({left:Number(el.dataset.railStep)*(rail.clientWidth+16),behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'});return}
 if(el.dataset.filter){state.filters=R.filterAction(state.filters,el.dataset.filter);if(['all','reset'].includes(el.dataset.filter))state.query='';render(false);return}
 if(el.dataset.sort){if(state.sort===el.dataset.sort)state.direction*=-1;else{state.sort=el.dataset.sort;state.direction=-1}render(false);return}
 if(el.dataset.chartMode){state.chartMode=el.dataset.chartMode;render(false);return}
 if(el.dataset.day){stopPlayback();setDay(Number(el.dataset.day));return}
 if(el.dataset.reviewTab){state.reviewTab=el.dataset.reviewTab;const y=window.scrollY;render(false);window.scrollTo({top:y,behavior:'instant'});return}
 if(el.dataset.journalMode){state.journalMode=el.dataset.journalMode;render(false);return}
 switch(el.dataset.action){
  case'all-updates':navigate('journal');state.journalMode='directions';state.journalDate=DATA.analysis_date;render(true);break;
  case'all-recommendations':navigate('records');state.filters={...R.defaultFilters(),scope:'both'};render(true);break;
  case'market-info':case'direction-info':case'filter-info':openInfo();document.getElementById(el.dataset.action.replace('-info','')+'Policy')?.scrollIntoView({block:'start'});break;
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
  case'read-full':state.reviewTab='latest';render(false);$('reviewPanel').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});break;
 }
});
document.addEventListener('input',e=>{
 if(e.target.id==='recordSearch'){state.query=e.target.value;$('tableRows').innerHTML=tableRows();$('tableEmpty').hidden=filteredStocks().length>0;$('tableCount').textContent=`${filteredStocks().length} 条记录`;}
 if(e.target.id==='commandInput'){state.searchIndex=0;searchResults();}
 if(e.target.id==='replayRange'){const day=Number(e.target.value);stopPlayback();setDay(day,false);refreshDetailDay();}
});
document.addEventListener('change',e=>{if(e.target.id==='journalDate'){state.journalDate=e.target.value;render(false)}});
document.addEventListener('input',e=>{if(e.target.id==='railScrollbar'){$('recommendationRail').scrollLeft=Number(e.target.value);}});
document.addEventListener('change',e=>{
 if(e.target.id==='deepEpisode'){state.heroRecord=Number(e.target.value);render(false);}
 if(e.target.id==='opinionFilter'){state.filters=R.filterAction(state.filters,'opinion',e.target.value);render(false);}
});
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
// 星图键盘可达：聚焦光点预览明细，Enter/Space 经通用 role=button 处理固定选中。
document.addEventListener('focusin',e=>{
 if(state.page!=='map')return;
 const dot=e.target.closest?.('.map-dot');if(!dot)return;
 state.mapPreview=state.mapMode==='stock'?dot.dataset.mapGroup:dot.dataset.mapId;
 updateMapPanel();
});
document.addEventListener('focusout',e=>{
 if(state.page!=='map'||!e.target.closest?.('.map-dot'))return;
 if(state.mapPreview!==null){state.mapPreview=null;updateMapPanel()}
});
window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{setupOverviewScroll();draw()},100)});
document.addEventListener('visibilitychange',()=>{if(document.hidden){stopPlayback();if(state.page==='detail')render(false)}});
if(readStore('guanlan.theme')==='light')document.body.classList.add('light');
// Bind snapshot metadata; never leave the demo's date/count in a new report.
const footerNode=$('snapshotFooter'),summaryNode=$('snapshotSummary'),timingNode=$('snapshotTiming');
if(footerNode)footerNode.textContent=`${sourceLabel()} · 行情截至 ${displayDate} · 非实时行情，非账户收益`;
if(summaryNode)summaryNode.textContent=`这是本地冻结复盘的独立交互展示稿。载入${stocks.length}条观察记录，不访问网络、不连接券商，也不生成新的选股结论。`;
if(timingNode)timingNode.textContent=`行情截至${DATA.analysis_date}。原快照截止为${DATA.as_of||'源报告未提供'}。逐日回看按复盘日期展示；部分报告在之后生成，因此这不是严格按当时可见信息运行的历史回测。`;
const availableMarkets=R.marketCards(DATA);
if($('marketSnapshotStatus'))$('marketSnapshotStatus').textContent=`本次快照：${availableMarkets.filter(x=>x.close!==null).length}/${availableMarkets.length}项已提供。${availableMarkets.filter(x=>x.close===null).length?'未提供或非本日数据：'+availableMarkets.filter(x=>x.close===null).map(x=>x.name).join('、')+'。':'所有配置指数均有本日收盘。'}`;
hydrate();refreshCounts();render();
// Exposed read-only inspection hooks for the included tests, not an external API.
window.GUANLAN={snapshot:DATA,getState:()=>({...state,favorites:[...state.favorites]}),core:C,rules:R};
})();
