/* Deterministic presentation helpers. No network access or research judgments. */
(function(root){
  'use strict';
  const valid=v=>typeof v==='number'&&Number.isFinite(v);
  const key=s=>`${s.code}:${s.recDate}`;
  // ---- 完整日期解析（唯一实现；rules.js/app.js 一律复用，不各写同年拼接）。 ----
  // sessionDates 是定位用的 ISO 交易日序列；旧快照的同年 MM-DD 在自洽时兼容，
  // 跨年/倒序/末日不一致时明确报错，不猜年份。
  const ISO=/^\d{4}-\d{2}-\d{2}$/;
  const resolved=new WeakMap();
  function resolveDates(d){
    if(!d||typeof d!=='object')throw new Error('快照数据缺失，无法解析日期');
    if(resolved.has(d))return resolved.get(d);
    const analysis=d.analysis_date;
    if(typeof analysis!=='string'||!ISO.test(analysis))throw new Error(`analysis_date 必须是 YYYY-MM-DD：${JSON.stringify(analysis)}`);
    const raw=d.dates;
    if(!Array.isArray(raw)||!raw.length)throw new Error('快照缺少非空 dates 交易日序列');
    let out;
    if(Array.isArray(d.sessionDates)){
      if(d.sessionDates.length!==raw.length)throw new Error(`sessionDates 长度 ${d.sessionDates.length} 与 dates 长度 ${raw.length} 不一致`);
      out=d.sessionDates.map(String);
      checkIso(out,'sessionDates');
    }else if(raw.every(x=>typeof x==='string'&&ISO.test(x))){
      out=raw.slice();
      checkIso(out,'dates');
    }else{
      if(!raw.every(x=>typeof x==='string'&&/^\d{2}-\d{2}$/.test(x)))
        throw new Error(`dates 既不是完整 ISO 也不是 MM-DD 序列：${JSON.stringify(raw.slice(0,3))}`);
      const year=analysis.slice(0,4);
      out=raw.map(x=>`${year}-${x}`);
      checkIso(out,'dates');
      if(out[out.length-1]!==analysis)
        throw new Error(`旧 MM-DD 序列末日 ${out[out.length-1]} 与 analysis_date ${analysis} 不一致，无法证明年份；请从原归档重新生成展示数据`);
    }
    if(out[out.length-1]!==analysis)throw new Error(`日期序列末日 ${out[out.length-1]} 与 analysis_date ${analysis} 不一致`);
    resolved.set(d,out);
    return out;
  }
  function checkIso(values,label){
    for(const value of values){
      if(!ISO.test(value)||Number.isNaN(Date.parse(`${value}T00:00:00Z`)))
        throw new Error(`${label} 含无效日期：${JSON.stringify(value)}`);
    }
    for(let i=1;i<values.length;i++){
      if(values[i]<=values[i-1])
        throw new Error(`${label} 不是严格递增的日期序列：${values[i-1]} → ${values[i]}；跨年或倒序无法定位日期，请从原归档重新生成展示数据`);
    }
  }
  const dateAt=(i,d)=>{const s=resolveDates(d);if(!Number.isInteger(i)||i<0||i>=s.length)throw new Error(`日期序号越界：${i}（共 ${s.length} 个交易日）`);return s[i];};
  const indexOfDate=(d,iso)=>resolveDates(d).indexOf(iso);
  // ---- 取价接口：显式区分 exact-date 与 last-available（F07）。 ----
  function quoteOnIndex(s,i){
    const c=s.candles[i];
    return c&&valid(c[3])?{i,c}:null;
  }
  function lastAvailableQuote(s,end){
    for(let i=Math.min(end,s.candles.length-1);i>=0;i--){
      const c=s.candles[i];
      if(c&&valid(c[3]))return {i,c};
    }
    return null;
  }
  const quoteAt=lastAvailableQuote; // 旧调用名：历史曲线最近有效价，不得冒充当日价。
  // 当日指标（exact-date）：报告日缺真实收盘时 ret/drawdown/remaining 为 null；
  // max/high 是已发生的历史极值，可独立保留（F07/T17）。
  function metrics(s,end){
    const empty={ret:null,max:null,drawdown:null,remaining:null,high:null,close:null};
    if(s.d0||!valid(s.ref)||s.ref<=0||!Number.isInteger(end)||end<s.recIndex)return empty;
    const post=s.candles.slice(s.recIndex,end+1);
    if(!post.length)return empty;
    const closes=post.map(c=>c&&valid(c[3])?c[3]:null);
    const peaks=closes.filter(valid),highs=post.map(c=>c&&valid(c[1])?c[1]:null).filter(valid);
    const peak=peaks.length?Math.max(...peaks):null,close=closes[closes.length-1];
    const ratio=(v,base)=>valid(v)&&valid(base)&&base>0?(v/base-1)*100:null;
    return {ret:ratio(close,s.ref),max:ratio(peak,s.ref),drawdown:ratio(close,peak),
      remaining:ratio(s.ref*1.2,close),high:highs.length?ratio(Math.max(...highs),s.ref):null,close};
  }
  function reviewAt(s,end,d){const date=dateAt(end,d);return [...s.reviews].filter(r=>r.date<=date).sort((a,b)=>a.date.localeCompare(b.date)).at(-1)||null;}
  function normalize(values,start,end){
    const base=values[start];return values.map((v,i)=>i>=start&&i<=end&&valid(v)&&valid(base)&&base>0?v/base*100:null);
  }
  function dayChange(s,end){const q=quoteOnIndex(s,end);if(!q)return null;const prev=s.candles[end-1];return prev&&valid(prev[3])&&prev[3]>0?(q.c[3]/prev[3]-1)*100:null;}
  function reviewTone(r){
    if(!r)return 'neutral';
    if(r.viewChange==='invalidated'||r.assessmentCode==='contradicted')return 'invalid';
    if(r.assessmentText==='推荐后的事实与核心预期相反')return 'invalid';
    if(r.assessmentText==='当初的核心判断已经明显减弱')return 'weak';
    if(r.assessmentText==='当初的核心预期目前得到支持')return 'support';
    if(r.assessmentText==='部分预期已发生，关键部分仍在验证')return 'partial';
    return 'neutral';
  }
  function daysAt(s,end){return s.d0?0:Math.max(0,Math.min(s.days,end-s.recIndex+1));}
  const api={valid,key,resolveDates,dateAt,indexOfDate,quoteOnIndex,lastAvailableQuote,quoteAt,metrics,reviewAt,normalize,dayChange,reviewTone,daysAt};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.GuanlanCore=api;
})(typeof window!=='undefined'?window:globalThis);
