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
const api={BASE_DIRECTIONS,DIRECTION_LABELS,OPINION_OPTIONS,INDEX_META,key,indexOfDate,latest,recommendations,deepReviews,direction,directionUpdates,isInvalid,opinionCode,opinionLabel,closeOnDate,returnOnDate,defaultFilters,filterAction,filterRecords,marketCards};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.GuanlanRules=api;
})(typeof window!=='undefined'?window:globalThis);
