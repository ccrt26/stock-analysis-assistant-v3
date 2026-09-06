/* Deterministic presentation helpers. No network access or research judgments. */
(function(root){
  'use strict';
  const valid=v=>typeof v==='number'&&Number.isFinite(v);
  const key=s=>`${s.code}:${s.recDate}`;
  const dateAt=(i,d)=>`${d.analysis_date.slice(0,4)}-${d.dates[i]}`;
  function quoteAt(s,end){
    for(let i=Math.min(end,s.candles.length-1);i>=0;i--){const c=s.candles[i];if(c&&valid(c[3]))return {i,c};}
    return null;
  }
  function metrics(s,end){
    const empty={ret:null,max:null,drawdown:null,remaining:null,high:null,close:null};
    if(s.d0||!valid(s.ref)||s.ref<=0||end<s.recIndex)return empty;
    const post=s.candles.slice(s.recIndex,end+1).filter(c=>c&&valid(c[3]));
    if(!post.length)return empty;
    const close=post.at(-1)[3],peak=Math.max(...post.map(c=>c[3]));
    const highs=post.map(c=>c[1]).filter(valid);
    return {ret:(close/s.ref-1)*100,max:(peak/s.ref-1)*100,drawdown:(close/peak-1)*100,
      remaining:(s.ref*1.2/close-1)*100,high:highs.length?(Math.max(...highs)/s.ref-1)*100:null,close};
  }
  function reviewAt(s,end,d){const date=dateAt(end,d);return [...s.reviews].filter(r=>r.date<=date).sort((a,b)=>a.date.localeCompare(b.date)).at(-1)||null;}
  function normalize(values,start,end){
    const base=values[start];return values.map((v,i)=>i>=start&&i<=end&&valid(v)&&valid(base)&&base>0?v/base*100:null);
  }
  function dayChange(s,end){const q=quoteAt(s,end);if(!q||q.i!==end)return null;const prev=s.candles[end-1];return prev&&valid(prev[3])&&prev[3]>0?(q.c[3]/prev[3]-1)*100:null;}
  function reviewTone(r){
    if(!r)return 'neutral';
    if(r.assessmentText==='推荐后的事实与核心预期相反')return 'invalid';
    if(r.assessmentText==='当初的核心判断已经明显减弱')return 'weak';
    if(r.assessmentText==='当初的核心预期目前得到支持')return 'support';
    if(r.assessmentText==='部分预期已发生，关键部分仍在验证')return 'partial';
    return 'neutral';
  }
  function daysAt(s,end){return s.d0?0:Math.max(0,Math.min(s.days,end-s.recIndex+1));}
  const api={valid,key,dateAt,quoteAt,metrics,reviewAt,normalize,dayChange,reviewTone,daysAt};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.GuanlanCore=api;
})(typeof window!=='undefined'?window:globalThis);
