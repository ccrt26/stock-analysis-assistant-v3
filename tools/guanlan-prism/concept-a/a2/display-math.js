/* Display-only math. No selection, forecasts or generated trading dates. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.PrismMath=api})(typeof globalThis!=='undefined'?globalThis:this,()=>{
'use strict';
const valid=n=>typeof n==='number'&&Number.isFinite(n);
function windowRows(rows,calendar,endDate,count){
 const end=calendar.indexOf(endDate);if(end<0)throw new RangeError('报告日不在已提供的交易日历中');
 const map=new Map(rows.map(r=>[r.date,r]));
 return Array.from({length:count},(_,i)=>{const date=calendar[end-count+1+i]||null;return {date,open:null,high:null,low:null,close:null,volumeShares:null,amountYuan:null,...(date?map.get(date):{})}});
}
const tickIndices=(count,step=5)=>Array.from({length:Math.floor(count/step)},(_,i)=>(i+1)*step-1);
function activity(rows,period=5,field='volumeShares'){
 const read=r=>valid(r?.[field])&&r[field]>=0?r[field]:null;
 const today=read(rows.at(-1)),previous=read(rows.at(-2));
 const before=rows.slice(Math.max(0,rows.length-1-period),rows.length-1).map(read).filter(valid);
 const base=before.length?before.reduce((a,b)=>a+b,0)/before.length:null;
 return {today,previous,base,n:before.length,period,ratio:valid(today)&&base>0?today/base:null,
 previousRatio:valid(previous)&&base>0?previous/base:null,previousPct:valid(today)&&previous>0?(today/previous-1)*100:null};
}
function monotoneSegments(points){
 if(points.length<2)return [];
 const n=points.length,h=[],d=[],m=[];
 for(let i=0;i<n-1;i++){h[i]=points[i+1][0]-points[i][0];if(h[i]<=0)throw new RangeError('x 必须严格递增');d[i]=(points[i+1][1]-points[i][1])/h[i]}
 if(n===2)m[0]=m[1]=d[0];else{
 const end=(h0,h1,d0,d1)=>{let v=((2*h0+h1)*d0-h0*d1)/(h0+h1);if(Math.sign(v)!==Math.sign(d0))return 0;if(Math.sign(d0)!==Math.sign(d1)&&Math.abs(v)>3*Math.abs(d0))return 3*d0;return v};
 m[0]=end(h[0],h[1],d[0],d[1]);m[n-1]=end(h[n-2],h[n-3],d[n-2],d[n-3]);
 for(let i=1;i<n-1;i++){if(d[i-1]*d[i]<=0)m[i]=0;else{const a=2*h[i]+h[i-1],b=h[i]+2*h[i-1];m[i]=(a+b)/(a/d[i-1]+b/d[i])}}
 }
 return points.slice(0,-1).map((p,i)=>[p,[p[0]+h[i]/3,p[1]+m[i]*h[i]/3],[points[i+1][0]-h[i]/3,points[i+1][1]-m[i+1]*h[i]/3],points[i+1]]);
}
function smoothPath(values,x,y){
 const groups=[];let group=[];values.forEach((v,i)=>{if(valid(v))group.push([x(i),y(v)]);else if(group.length){groups.push(group);group=[]}});if(group.length)groups.push(group);
 const f=p=>p.map(v=>Number(v.toFixed(3))).join(',');
 return groups.map(ps=>`M${f(ps[0])}`+monotoneSegments(ps).map(s=>`C${f(s[1])} ${f(s[2])} ${f(s[3])}`).join('')).join(' ');
}
const normalize=(values,index)=>values.map(v=>valid(v)&&valid(values[index])&&values[index]>0?v/values[index]*100:null);
const averageSeries=(values,n)=>values.map((v,i)=>{const a=values.slice(i-n+1,i+1);return i>=n-1&&a.length===n&&a.every(valid)?a.reduce((s,x)=>s+x,0)/n:null});
return Object.freeze({valid,windowRows,tickIndices,activity,monotoneSegments,smoothPath,normalize,averageSeries});
});
