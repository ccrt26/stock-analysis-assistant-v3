/* Adapts a copy of the frozen snapshot + optional, preview-only daily history.
 * Existing candles are [open, high, low, close, amount_in_100m_CNY], NOT volume.
 * A.02 仓库版：方向、详评名单、观点更新、失效等业务口径只来自注入的仓库规则
 * （rules，镜像 src/rules.js），本文件不再内置第二套业务引擎；
 * 只负责补充行情合并、交易日对齐、指数历史与比较序列。无请求、不预测。 */
(function(root){'use strict';
const M=root.PrismMath,V=M.valid;
function create(data,extra={},rules){
 if(!rules||!rules.key||!rules.direction||!rules.deepReviews)
  throw new Error('A.02 数据适配必须注入仓库显示规则（rules），不允许内置第二套业务引擎');
 if(data.monitorReviewPolicy==='state-change-v1'){
  // The report is the sole source of changed-stock prose. Do not apply the
  // legacy eight-stock editorial cap or the old supplied detail list.
  rules.deepReviews=d=>{
   const groups=[];
   for(const stock of d.stocks){
    const review=rules.latest(stock);
    if(review?.date!==d.analysis_date||review.review_kind!=='regular_detail')continue;
    let group=groups.find(item=>item.code===stock.code);
    if(!group){group={code:stock.code,records:[]};groups.push(group);}
    if(!group.records.some(item=>rules.key(item.s)===rules.key(stock)))group.records.push({s:stock,r:review});
   }
   return {groups,totalStocks:groups.length,limit:groups.length,overflow:0,source:'当日状态变化'};
  };
  const legacyInvalid=rules.isInvalid;
  rules.isInvalid=(stock,day)=>{
   const review=rules.latest(stock,day||data.analysis_date);
   if(review?.trackingEndReason==='observation_complete')return false;
   if(review?.trackingEndReason==='thesis_invalidated')return true;
   return legacyInvalid(stock,day);
  };
  root.isInvalid=rules.isInvalid;
 }
 const end=data.analysis_date;
 const original=data.sessionDates||(data.dates||[]);
 if(!/^\d{4}-\d{2}-\d{2}$/.test(end)||!original.every(d=>/^\d{4}-\d{2}-\d{2}$/.test(d)))throw new Error('需要完整 ISO sessionDates，不能用 MM-DD 猜年份');
 if(!original.length||original.at(-1)!==end||original.some((d,i)=>i>0&&d<=original[i-1]))throw new Error('冻结交易日历必须严格递增且末日等于报告日');
 if((extra.sessionDates||[]).some(d=>!/^\d{4}-\d{2}-\d{2}$/.test(d)))throw new Error('补充日历需要完整日期');
 const sessions=[...new Set([...original,...(extra.sessionDates||[])])].filter(d=>d<=end).sort();
 if(!sessions.includes(end))throw new Error('报告日不在已提供的交易日历中');
 const issues=[];
 const originalSet=new Set(original);
 function history(s){
  const addition=extra.stocks?.[s.code];const supplement=new Map((addition?.priceBasis==='raw_unadjusted'?(addition.rows||[]):[]).filter(r=>r.date<=end).map(r=>[r.date,r]));
  const frozen=new Map(original.map((date,i)=>[date,s.candles?.[i]||null]));
  return sessions.map(date=>{const a=supplement.get(date)||{},c=frozen.get(date);let conflict=c&&V(c[3])&&V(a.close)&&Math.abs(c[3]-a.close)>0.005;
   if(conflict&&!issues.includes(`${s.code} ${date} 补充行情与原快照不一致`))issues.push(`${s.code} ${date} 补充行情与原快照不一致`);
   // Frozen prices have precedence, even frozen missing values within the original calendar.
   let r=originalSet.has(date)?{date,open:c?.[0]??null,high:c?.[1]??null,low:c?.[2]??null,close:c?.[3]??null,amountYuan:V(c?.[4])?c[4]*1e8:null}:{date,...a};
   r.volumeShares=!conflict&&V(a.volumeShares)&&a.volumeShares>=0?a.volumeShares:null;
   return r;
  });
 }
 const quote=s=>history(s).find(r=>r.date===end)||{};
 function comparison(s,field){const base=field==='stock'?history(s).map(r=>r.close):field==='industry'?sessions.map(date=>{
  // 原快照日历内沿用该记录行业数组（含 null，不被补充覆盖）；
  // 原日历之外，携带 industryCode 的主题记录读取 comparisons 同日期官方收盘。
  if(originalSet.has(date)){const v=s.industry?.[original.indexOf(date)];return v==null?null:v}
  const code=s.industryCode;
  if(code){const row=(extra.comparisons?.[code]?.rows||[]).find(r=>r.date===date);if(row&&row.close!=null)return row.close}
  return extra.stocks?.[s.code]?.industry?.find(r=>r.date===date)?.close ?? null;
 }):sessions.map(date=>originalSet.has(date)?data.market?.[original.indexOf(date)]??null:extra.indices?.[data.presentation?.marketCodes?.[0]]?.rows?.find(r=>r.date===date)?.close??null);return M.normalize(base,sessions.indexOf(s.recDate))}
 function markets(){const codes=data.presentation?.marketCodes||(data.market?.length?['000001.SH']:[]);return codes.map(code=>{let m=(data.marketIndices||[]).find(m=>m.code===code);if(!m&&code==='000001.SH')m={code,name:data.market_name,trade_date:end,close:data.market.at(-1),previousClose:data.market.at(-2),series:data.market};return m||{code,name:code,series:[],close:null}})}
 function indexHistory(m){const extraRows=(extra.indices?.[m.code]?.rows||[]).filter(r=>r.date<=end);return sessions.map(date=>{let r=extraRows.find(r=>r.date===date);if(date===end&&m.trade_date===end&&V(m.close)&&V(r?.close)&&Math.abs(m.close-r.close)>0.005){const message=`${m.code} ${date} 指数补充收盘与冻结值不一致`;if(!issues.includes(message))issues.push(message);r=null}return {date,open:null,high:null,low:null,close:null,volumeShares:null,amountYuan:null,...r}})}
 return {data,extra,end,sessions,original,issues,
  key:s=>rules.key(s),
  ordered:s=>rules.orderedReviews(s,end),
  latest:s=>rules.latest(s),
  direction:r=>rules.direction(r),
  dirLabels:rules.DIRECTION_LABELS,
  invalid:s=>rules.isInvalid(s),
  opinion:s=>rules.opinionLabel(s),
  history,quote,
  ret:s=>rules.returnOnDate(s),
  daysObserved:s=>rules.daysAt(s),
  recommendations:rules.recommendations(data),
  deep:rules.deepReviews(data).groups.map(g=>({code:g.code,records:g.records.map(x=>x.s)})),
  updates:rules.directionUpdates(data),
  comparison,markets,indexHistory};
}
root.PrismData={create};
})(globalThis);
