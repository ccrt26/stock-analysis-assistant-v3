/* PRISM V3 · Display policy, not a stock-selection or research engine.
 * All dates refer to snapshot.analysis_date (the reviewed trading day).
 * No network, guessed prices, prose analysis, or hardcoded company selection.
 */
(function(root){
'use strict';
const valid=v=>typeof v==='number'&&Number.isFinite(v);
const key=s=>`${s.code}:${s.recDate}`;
const dateAt=(i,d)=>d.dates[i]?.length===10?d.dates[i]:`${d.analysis_date.slice(0,4)}-${d.dates[i]}`;
const indexOfDate=d=>d.dates.findIndex((_,i)=>dateAt(i,d)===d.analysis_date);
function orderedReviews(s,date){return (s.reviews||[]).filter(r=>r.date<=date).slice().sort((a,b)=>a.date.localeCompare(b.date)||(a.as_of||'').localeCompare(b.as_of||''));}
function latest(s,d){return orderedReviews(s,d.analysis_date).at(-1)||null;}
function recommendations(d){return [...d.stocks].sort((a,b)=>b.recDate.localeCompare(a.recDate));}
function deepReviews(d){
 const rawLimit=d.presentation?.deepLimit;
 const limit=valid(rawLimit)?Math.min(8,Math.max(0,Math.floor(rawLimit))):8;
 const supplied=d.dailyDeepReview;
 const candidates=d.stocks.flatMap(s=>{
  const r=latest(s,d);
  return r?.date===d.analysis_date&&r.review_kind==='regular_detail'&&!s.d0?[{s,r}]:[];
 });
 // An explicit upstream selection is authoritative, including an empty list.
 let ordered=candidates;
 if(supplied){
  const keys=supplied.date===d.analysis_date?(supplied.recordKeys||[]):[];
  ordered=keys.map(k=>candidates.find(x=>key(x.s)===k)).filter(Boolean);
 }
 const groups=[];
 for(const x of ordered){
  let group=groups.find(g=>g.code===x.s.code);
  if(!group){group={code:x.s.code,records:[]};groups.push(group);}
  if(!group.records.some(y=>key(y.s)===key(x.s)))group.records.push(x);
 }
 return {groups:groups.slice(0,limit),totalStocks:groups.length,limit,
  source:supplied?'当日上游详评名单':'当日 regular_detail 标记',overflow:Math.max(0,groups.length-limit)};
}
// Exact legacy-field aliases. These describe the source's 1–3 day outlook,
// NOT the realised daily return, current_path, or original-thesis confidence.
const BASE_DIRECTIONS=Object.freeze({
 '未来1—3个交易日更可能震荡偏强':'up',
 '未来1—3个交易日更可能继续走强':'up',
 '未来1—3个交易日更可能横盘整理或等待新变化':'sideways',
 '未来1—3个交易日更可能震荡偏下':'down',
 '未来1—3个交易日更可能继续偏弱':'down',
 '未来1—3个交易日更可能高位剧烈波动并出现回吐':'down'
});
const DIRECTION_LABELS=Object.freeze({up:'上涨',sideways:'横盘',down:'下跌'});
function direction(r){
 if(!r)return null;
 if(Object.prototype.hasOwnProperty.call(r,'outlookDirection'))return DIRECTION_LABELS[r.outlookDirection]?r.outlookDirection:null;
 return BASE_DIRECTIONS[r.base]||null;
}
function directionUpdates(d){
 return recommendations(d).flatMap(s=>{
  const rows=orderedReviews(s,d.analysis_date),r=rows.at(-1);
  if(!r||r.date!==d.analysis_date)return [];
  const previous=rows.filter(x=>x.date<r.date).at(-1);
  const from=direction(previous),to=direction(r);
  if(!from||!to||from===to)return [];
  return [{s,r,previous,from,to,reason:r.viewReason||r.outlookReason||'',fromLabel:DIRECTION_LABELS[from],toLabel:DIRECTION_LABELS[to]}];
 });
}
function isInvalid(s,d){
 // Optional current lifecycle value must be copied from the research system.
 if(typeof s.invalidated==='boolean')return s.invalidated;
 const r=latest(s,d);
 if(r)return r.viewLabel==='判断失效'||r.assessmentText==='推荐后的事实与核心预期相反';
 return ['原判断失效','判断失效'].includes(s.stage);
}
const OPINION_OPTIONS=Object.freeze([
 {value:'any',label:'全部复盘观点'},
 {value:'strengthened',label:'观点增强'},
 {value:'weakened',label:'观点减弱'},
 {value:'maintained',label:'维持原判'},
 {value:'first',label:'首次复盘'},
 {value:'unreviewed',label:'尚未复盘'}
]);
function opinionCode(s,d){
 if(isInvalid(s,d))return 'invalidated';
 const label=latest(s,d)?.viewLabel;
 return ({'观点增强':'strengthened','观点减弱':'weakened','维持原判断':'maintained','维持原判':'maintained','首次复盘':'first'})[label]||'unreviewed';
}
function opinionLabel(s,d){const code=opinionCode(s,d);return code==='invalidated'?'判断失效':OPINION_OPTIONS.find(x=>x.value===code)?.label||'尚未复盘';}
function closeOnDate(s,d){
 const i=indexOfDate(d);if(i<0)return null;
 const close=s.candles[i]?.[3];return valid(close)?close:null;
}
function returnOnDate(s,d){
 const close=closeOnDate(s,d),i=indexOfDate(d);
 return s.d0||!valid(s.ref)||s.ref<=0||close===null||i<s.recIndex?null:(close/s.ref-1)*100;
}
function defaultFilters(){return {scope:'default',positive:false,opinion:'any'};}
function filterAction(f,action,value){
 if(action==='all')return {...defaultFilters(),scope:'active'};
 if(action==='reset')return defaultFilters();
 if(action==='invalid')return {...f,scope:({default:'invalid',invalid:'default',active:'both',both:'active'})[f.scope]||'invalid',opinion:'any'};
 if(action==='only-invalid')return {...defaultFilters(),scope:'invalid'};
 if(action==='positive')return {...f,positive:!f.positive};
 if(action==='opinion'){
  const known=OPINION_OPTIONS.some(x=>x.value===value);
  return {...f,opinion:known?value:'any',scope:value!=='any'?'active':f.scope};
 }
 return {...f};
}
function filterRecords(d,f){return recommendations(d).filter(s=>{
 const invalid=isInvalid(s,d);
 if(f.scope==='invalid'&&!invalid)return false;
 if(!['invalid','both'].includes(f.scope)&&invalid)return false;
 const ret=returnOnDate(s,d);
 if(f.positive&&(ret===null||ret<=0))return false;
 if(f.opinion!=='any'&&opinionCode(s,d)!==f.opinion)return false;
 return true;
});}
const INDEX_META=Object.freeze({
 '000001.SH':{name:'上证指数',description:'沪市市场观察'},
 '399001.SZ':{name:'深证成指',description:'深市市场观察'},
 '399006.SZ':{name:'创业板指',description:'创业板市场观察'},
 '000688.SH':{name:'科创50',description:'科创板代表指数'},
 '899050.BJ':{name:'北证50',description:'北交所市场观察'}
});
function marketCards(d){
 const codes=[...new Set(d.presentation?.marketCodes||['000001.SH','399001.SZ','399006.SZ','000688.SH'])];
 const i=indexOfDate(d);
 return codes.map(code=>{
  let row=(d.marketIndices||[]).find(x=>x.code===code);
  if(!row&&code==='000001.SH'&&d.market_name==='上证指数'&&i>=0){
   row={code,name:d.market_name,trade_date:d.analysis_date,close:d.market[i],previousClose:d.market[i-1],
    series:d.market.slice(0,i+1),source:'上传报告 market 价格序列'};
  }
  const meta=INDEX_META[code]||{},fresh=row?.trade_date===d.analysis_date;
  const close=fresh&&valid(row?.close)?row.close:null;
  const previousClose=fresh&&valid(row?.previousClose)&&row.previousClose>0?row.previousClose:null;
  const changePct=close!==null&&previousClose!==null?(close/previousClose-1)*100:null;
  return {code,name:row?.name||meta.name||code,description:row?.description||meta.description||'研究市场基准',
   close,previousClose,changePct,change:close!==null&&previousClose!==null?close-previousClose:null,
   series:fresh?(row?.series||[]):[],source:row?.source||'当前快照未提供',trade_date:row?.trade_date||null,
   status:close!==null?'available':row&&!fresh?'stale':'missing'};
 });
}
// ---- 观察星图：同股合并（仅展示层派生，冻结输入与记录身份不改）。 ----
// 输入历史无法证明覆盖完整推荐史，界面对外只能称“本报告最早记录”，不得称历史首次。
const ATLAS_BASIS_LABEL='本报告最早记录';
function atlasGroups(d){
 // 按完整股票代码（含交易所）分组，不按中文名；原始 stocks 数组与顺序不动。
 // 独立身份沿用 code:recDate：同一身份重复载入只算一次入选，也不按收益另选副本。
 const byCode=new Map();
 for(const s of d.stocks){
  let g=byCode.get(s.code);
  if(!g){g={code:s.code,name:s.name,records:[]};byCode.set(s.code,g);}
  if(!g.records.some(x=>key(x)===key(s)))g.records.push(s);
 }
 const groups=[...byCode.values()];
 for(const g of groups)g.records.sort((a,b)=>a.recDate.localeCompare(b.recDate));
 groups.sort((a,b)=>a.records[0].recDate.localeCompare(b.records[0].recDate));
 return groups;
}
function atlasGroupClose(records,d){
 // 价格属于股票不属于推荐：同股同日（dates 同一序号）的有效收盘取第一份副本；
 // 不跨日拼接、不叠加，任何一条都不用上一交易日价格冒充报告日价格。
 const i=indexOfDate(d);if(i<0)return null;
 for(const s of records){const c=s.candles[i]?.[3];if(valid(c))return c;}
 return null;
}
function atlasPlottable(s,close,d){
 // 返回不可绘制原因；null 表示该记录可绘制。绝不静默换基准或按 0% 绘制。
 if(s.d0)return '待首日观察';
 if(!valid(s.ref)||s.ref<=0)return '缺参考价';
 const i=indexOfDate(d);
 if(i<0||!valid(s.recIndex)||s.recIndex<0||s.recIndex>i)return '交易日历不足';
 if(!valid(close))return '报告日无真实收盘';
 return null;
}
function atlasBasis(group,d){
 // 股票视图主点：最早入选日+原参考价+该日到报告日的交易日序号成套使用；
 // 之后再入选只更新次数与明细，不替换锚点，不平均、不挑选收益更好的一次。
 const anchor=group.records[0];
 const close=atlasGroupClose(group.records,d);
 const reason=atlasPlottable(anchor,close,d);
 if(reason)return {anchor,close,plottable:false,reason,ret:null,day:null};
 const i=indexOfDate(d);
 return {anchor,close,plottable:true,reason:null,ret:(close/anchor.ref-1)*100,day:i-anchor.recIndex+1};
}
function atlasRecordPoint(s,group,d){
 // 记录视图点：用该次自己的参考价与交易日序号；报告日收盘与股票视图同源同日。
 const close=atlasGroupClose(group.records,d);
 const reason=atlasPlottable(s,close,d);
 if(reason)return {s,close,plottable:false,reason,ret:null,day:null};
 const i=indexOfDate(d);
 return {s,close,plottable:true,reason:null,ret:(close/s.ref-1)*100,day:i-s.recIndex+1};
}
function atlasBadge(group){
 // 次数=本报告包含的独立入选记录数；每天复盘与重复载入不计数，不代表终身次数。
 const n=group.records.length;if(n<2)return null;
 const pending=group.records.filter(s=>s.d0).length;
 const events=group.records.filter(s=>s.refKind==='event').length;
 const tags=[];
 if(events===n)tags.push('条件观察');else if(events)tags.push('含条件观察');
 if(pending)tags.push(`含${pending}次待首日`);
 return {count:n,short:`入选 ${n} 次`,full:`入选 ${n} 次`+(tags.length?` · ${tags.join(' · ')}`:'')};
}
function atlasRange(stockPoints,recordPoints){
 // 两种模式共用同一真实数据范围：必含 0 与全部可绘制点并留余量，不做固定 ±12% 裁切。
 const rets=[],days=[];
 for(const p of[...stockPoints,...recordPoints])if(p.plottable){rets.push(p.ret);days.push(p.day);}
 if(!rets.length)return null;
 let lo=Math.min(0,...rets),hi=Math.max(0,...rets);
 const pad=Math.max((hi-lo)*.18,1.2);lo-=pad;hi+=pad;
 return {lo,hi,maxDay:Math.max(...days,1),basis:ATLAS_BASIS_LABEL};
}
const api={BASE_DIRECTIONS,DIRECTION_LABELS,OPINION_OPTIONS,INDEX_META,ATLAS_BASIS_LABEL,key,indexOfDate,latest,recommendations,deepReviews,direction,directionUpdates,isInvalid,opinionCode,opinionLabel,closeOnDate,returnOnDate,defaultFilters,filterAction,filterRecords,marketCards,atlasGroups,atlasGroupClose,atlasPlottable,atlasBasis,atlasRecordPoint,atlasBadge,atlasRange};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.GuanlanRules=api;
})(typeof window!=='undefined'?window:globalThis);
