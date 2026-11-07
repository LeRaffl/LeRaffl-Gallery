#!/usr/bin/env python3
"""Execute the actual Raw Data JS in Node with a small DOM double (no network).

Run: python scripts/test_raw_data_fuels.py. Node is available on CI runners.
These behavior/geometry checks complement, not replace, visual browser testing.
"""
import json
import subprocess
from pathlib import Path

html = (Path(__file__).resolve().parent.parent / 'index.html').read_text(encoding='utf-8')
start = html.index('/* ── Raw Data tab', html.index('/* ── Raw Data tab') + 1)
raw = html[start:html.index('// -------- Plotly chart download helper', start)]
raw = raw[:raw.rindex('})();')] + '''
  globalThis.rawTest = {selectedTotal, displayValue, axisMaximum, plotKeys,
    availableFuels, plan, bars, paintFuels, drawPlot, render, wire, csvText,
    downloadCSV, svgToDataURL, stateHash, shareURL, readHash, writeHash,
    validateBreakdowns, completeSelection, combined,
    state:()=>S, setState:s=>Object.assign(S,s),
    setData:d=>{DATA=d;NAMES=Object.keys(d).sort();},
    setView:(v,sum=null)=>{VIEW=v;SUM=sum;}};
})();
'''
raw += html[html.index('  function ttmFromSeries(j)'):html.index('  function loadObs(countries)')]
js = r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
let count=0;function test(name,fn){fn();count++;console.log('ok  '+name);}
const plain=x=>JSON.parse(JSON.stringify(x));
class Classes{
 constructor(){this.s=new Set();} add(x){this.s.add(x);} remove(x){this.s.delete(x);}
 contains(x){return this.s.has(x);} toggle(x,on){if(on)this.add(x);else this.remove(x);}
}
const downloads=[];
class Element{
 constructor(){this.dataset={};this.classList=new Classes();this.children=[];this.clientWidth=600;
  this.style={};this.tip={innerHTML:'',classList:new Classes()};}
 set innerHTML(h){this.html=h;this.children=[];
  this.inputs=[...h.matchAll(/data-fuel="([^"]+)"/g)].map(m=>({dataset:{fuel:m[1]},checked:false,
   parentElement:{classList:new Classes()},matches:()=>true}));
  this.hits=[...h.matchAll(/class="rd-hit" data-i="(\d+)"/g)].map(m=>({dataset:{i:m[1]},
   events:{},addEventListener(k,f){this.events[k]=f;}}));}
 get innerHTML(){return this.html||'';}
 querySelector(s){return s==='.rd-tip'?this.tip:null;}
 querySelectorAll(s){return s==='input[data-fuel]'?(this.inputs||[]):s==='.rd-hit'?(this.hits||[]):[];}
 appendChild(e){this.children.push(e);} addEventListener(){} setAttribute(k,v){this[k]=v;}
 focus(){} click(){downloads.push(this);}
}
const elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
let exportedBlob=null,replacedURL='';
URL.createObjectURL=b=>{exportedBlob=b;return 'blob:test';};URL.revokeObjectURL=()=>{};
const ctx={console,URL,URLSearchParams,Blob,Date,Math,Set,Map,BigInt,
 tok:(_n,f)=>f,btoa:s=>Buffer.from(s,'binary').toString('base64'),unescape,encodeURIComponent,
 setTimeout:f=>{f();return 0;},clearTimeout:()=>{},
 location:{href:'https://example.test/index.html',hash:'#not-active'},
 history:{replaceState(_a,_b,u){replacedURL=u;}},window:{addEventListener(){}},
 document:{getElementById:el,querySelectorAll:()=>[],addEventListener(){},createElement:()=>new Element()}};
vm.createContext(ctx);vm.runInContext(SOURCE,ctx);const r=ctx.rawTest;
const state={c:['A'],n:1,u:'abs',t:0,qr:false,ax:0,q:1,f:null};
const bar={from:24000,to:24000,span:1,tot:1000,v:{BEV:10,PHEV:20,ICE:970},scale:1};
function series(v={BEV:10,PHEV:20,ICE:970},total=1000,extra={}){
 return {source:'fixture',step:1,ice_split:false,hybrid_combined:false,m:[24000,24001,24002],g:[1,1,1],
 t:[total,total,total],b:Object.fromEntries(Object.entries(v).map(([k,n])=>[k,[n,n,n]])),
 held_from:'2000-01',dropped:0,folded:[],...extra};}
function reset(data={A:series()}){r.setData(data);r.setState({...state});r.setView([]);}
function draw(list=[bar],compact=false){const e=new Element();r.drawPlot(e,{title:'fixture',sub:'registrations',
 list,compact,step:1,dom:[23999.5,24000],ymax:0,qr:null});return e;}
reset();
test('default All preserves total axis and existing bands',()=>{
 assert.equal(r.axisMaximum([bar]),1000);assert.deepEqual(plain(r.plotKeys([bar])),['BEV','PHEV','ICE']);});
test('single fuel and coarse-window axes use selected stack',()=>{
 r.setState({f:['BEV']});assert.equal(r.selectedTotal(bar),10);assert.equal(r.axisMaximum([bar]),10);
 assert.equal(r.axisMaximum([{...bar,v:{BEV:120,ICE:11880},tot:12000,scale:1/12}]),10);});
test('combinations sum only selected bands',()=>{
 r.setState({f:['BEV','PHEV']});assert.equal(r.selectedTotal(bar),30);assert.equal(r.axisMaximum([bar]),30);});
test('Share always uses original TOTAL, never selected sum',()=>{
 r.setState({f:['BEV'],u:'rel'});assert.equal(r.displayValue(bar,'BEV'),.01);
 assert.equal(r.displayValue({...bar,tot:0},'BEV'),0);});
test('actual absolute SVG draws only chosen fuel on chosen scale',()=>{
 r.setState({u:'abs'});const e=draw();assert.match(e.innerHTML,/>10<\/text>/);
 assert.doesNotMatch(e.innerHTML,/>1000<\/text>|fill="#4f9fe0"|fill="#a65832"/);
 assert.match(e.innerHTML,/fill="#2e8b57"/);});
test('actual tooltip separates selected sum and original TOTAL',()=>{
 const e=draw();e.hits[0].events.mouseenter();assert.match(e.tip.innerHTML,/Selected/);
 assert.match(e.tip.innerHTML,/TOTAL \(all bands\)/);assert.match(e.tip.innerHTML,/1,000/);
 assert.doesNotMatch(e.tip.innerHTML,/PHEV/);});
test('Share tooltip is 1%, not 100%',()=>{
 r.setState({u:'rel'});const e=draw();e.hits[0].events.mouseenter();
 assert.match(e.tip.innerHTML,/1\.0%/);assert.doesNotMatch(e.tip.innerHTML,/100\.0%/);});
test('reported zero stays selectable with finite geometry',()=>{
 r.setState({u:'abs'});const b={...bar,v:{BEV:0,ICE:1000}};
 assert.equal(r.axisMaximum([b]),1);assert.deepEqual(plain(r.plotKeys([b])),['BEV']);
 assert.match(draw([b]).innerHTML,/<svg/);assert.doesNotMatch(draw([b]).innerHTML,/NaN|Infinity/);});
test('common ICE collapse stays disjoint and counts once',()=>{
 reset({A:series({BEV:10,PETROL:80,DIESEL:10},100,{ice_split:true}),B:series()});
 const p=r.plan(['A','B']),a=plain(r.availableFuels(['A','B'],p));
 assert(a.includes('ICE'));assert(!a.includes('PETROL'));assert(!a.includes('DIESEL'));
 const b=r.bars('A',1,p)[0];assert.equal(b.v.ICE,90);assert.equal(b.tot,100);});
test('combined Hybrid does not invent separately selectable PHEV',()=>{
 reset({A:series(),B:series({BEV:10,Hybrid:30,ICE:960},1000,{hybrid_combined:true})});
 const a=plain(r.availableFuels(['A','B'],r.plan(['A','B'])));assert(a.includes('Hybrid'));assert(!a.includes('PHEV'));});
test('future artifact keys work without registry changes',()=>{
 reset({A:series({BEV:10,EXTRA:2,ICE:988})});r.setState({f:['EXTRA']});
 assert(plain(r.availableFuels(['A'],r.plan(['A']))).includes('EXTRA'));
 assert.deepEqual(plain(r.plotKeys([{...bar,v:{EXTRA:2}}])),['EXTRA']);assert.match(draw([{...bar,v:{EXTRA:2}}]).innerHTML,/EXTRA/);});
test('hash and QR share all settings, including fuels and quality',()=>{
 reset();r.setState({f:['PHEV','BEV'],q:0});const h=r.stateHash();assert.match(h,/f=BEV,PHEV/);
 assert.match(h,/q=0/);assert(r.shareURL().endsWith(h));ctx.location.hash=h;r.setState({f:null});
 r.readHash();assert.deepEqual(plain(r.state().f),['BEV','PHEV']);r.writeHash();assert.equal(replacedURL,'');});
test('None roundtrips distinctly; links without f restore All',()=>{
 r.setState({f:[]});const h=r.stateHash();assert.match(h,/&f=$/);ctx.location.hash=h;r.setState({f:null});
 r.readHash();assert.deepEqual(plain(r.state().f),[]);ctx.location.hash='#rawdata?c=A&n=1&u=abs';
 r.readHash();assert.equal(r.state().f,null);r.setState({f:['BEV']});ctx.location.hash='#rawdata';
 r.readHash();assert.equal(r.state().f,null);});
test('URL deduplicates future keys and rejects invalid tokens',()=>{
 ctx.location.hash='#rawdata?c=A&f=EXTRA,EXTRA,%3Cscript%3E';r.readHash();assert.deepEqual(plain(r.state().f),['EXTRA']);
 ctx.location.hash='#rawdata?c=A&f=*';r.readHash();assert.equal(r.state().f,null);});
test('browser hash writer matches QR serializer',()=>{
 r.setState({f:['BEV']});ctx.location.hash='#rawdata';r.writeHash();
 assert.equal(replacedURL,'https://example.test/index.html'+r.stateHash());assert(r.shareURL().endsWith(r.stateHash()));});
test('default CSV retains existing column layout and counts',()=>{
 reset();r.setView([{c:'A',l:[bar]}]);assert.equal(r.csvText(),
 'series,window_months,period_from,period_to,BEV,PHEV,ICE,TOTAL\n"A",1,2000-01,2000-01,10,20,970,1000');});
test('filtered CSV contains chosen columns, selected sum, full TOTAL',()=>{
 r.setState({f:['BEV'],u:'rel'});assert.equal(r.csvText(),
 'series,window_months,period_from,period_to,BEV,SELECTED_TOTAL,TOTAL\n"A",1,2000-01,2000-01,10,10,1000');});
test('coarse CSV uses documented full-window count convention',()=>{
 const b={...bar,from:24000,to:24011,span:12,scale:1/12,tot:12000,v:{BEV:120,ICE:11880}};
 r.setView([{c:'A',l:[b]}]);r.setState({u:'abs'});assert.equal(r.displayValue(b,'BEV'),10);
 assert.match(r.csvText(),/,120,120,12000$/);});
test('CSV omits countries without selected band rather than inventing zero',()=>{
 r.setView([{c:'A',l:[bar]},{c:'B',l:[{...bar,v:{Hybrid:50,ICE:950}}]}]);
 assert.match(r.csvText(),/"A"/);assert.doesNotMatch(r.csvText(),/"B"/);});
test('PNG SVG input contains filtered geometry and fuel caption',()=>{
 const e=draw(),svg={outerHTML:e.innerHTML.split('</svg>')[0]+'</svg>',getAttribute:()=> '0 0 600 330'};
 const text=Buffer.from(r.svgToDataURL(svg).split(',')[1],'base64').toString('utf8');
 assert.match(text,/Fuels: BEV/);assert.doesNotMatch(text,/fill="#4f9fe0"|fill="#a65832"/);});
test('compact PNG SVG carries its own selection caption',()=>{assert.match(draw([bar],true).innerHTML,/Fuels: BEV/);});
test('render uses selected shared scale across individual charts',()=>{
 reset({A:series({BEV:10,ICE:990}),B:series({BEV:20,ICE:1980},2000)});
 r.setState({c:['A','B'],f:['BEV'],ax:1});r.render();assert.equal(el('rdPlots').children.length,2);
 el('rdPlots').children.forEach(e=>{assert.match(e.innerHTML,/>20<\/text>/);assert.doesNotMatch(e.innerHTML,/>2000<\/text>/);});
 assert.equal(el('rdDlCsv').disabled,false);});
test('None clears plots and disables both exports',()=>{
 r.wire();el('rdFuelNone').onclick();assert.deepEqual(plain(r.state().f),[]);assert.match(el('rdPlots').innerHTML,/No fuel selected/);
 assert.equal(el('rdDlCsv').disabled,true);assert.equal(el('rdDlPng').disabled,true);assert.equal(r.csvText(),'');});
test('All restores current bands; checkbox toggle preserves focus node',()=>{
 el('rdFuelAll').onclick();assert.equal(r.state().f,null);const host=el('rdFuelList'),c=host.inputs.find(i=>i.dataset.fuel==='ICE');
 c.checked=false;host.onchange({target:c});assert.deepEqual(plain(r.state().f),['BEV']);
 assert.equal(host.inputs.find(i=>i.dataset.fuel==='ICE'),c);assert.equal(c.parentElement.classList.contains('on'),false);});
test('country changes refresh options and explain unavailable preferences',()=>{
 r.setData({A:series({BEV:10,Hybrid:30,ICE:960},1000,{hybrid_combined:true})});r.setState({c:['A'],f:['PHEV']});r.render();
 assert(!el('rdFuelList').inputs.some(i=>i.dataset.fuel==='PHEV'));assert.match(el('rdFuelHint').textContent,/not separately available here: PHEV/);
 assert.match(el('rdPlots').innerHTML,/not separately available/);assert.equal(el('rdDlCsv').disabled,true);
 el('rdFuelAll').onclick();assert.equal(r.state().f,null);assert.equal(el('rdDlCsv').disabled,false);});

function detailed(values,g=1){
 const n=values.length;return series({BEV:10,ICE:80,OTHERS:10},100,{
  m:Array.from({length:n},(_,i)=>24000+i),g:Array(n).fill(1),t:Array(n).fill(100),
  b:{BEV:Array(n).fill(10),ICE:Array(n).fill(80),OTHERS:Array(n).fill(10)},
  breakdown:{FCEV:{parent:'OTHERS',v:values,g:Array(n).fill(g)}}});
}
test('confirmed detail is a disjoint raw leaf, not an extra addend',()=>{
 reset({A:detailed([null,2,0])});const bars=r.bars('A',1,r.plan(['A']));
 assert.equal(bars[0].v.FCEV,null);assert.equal(bars[0].v.OTHERS,10);
 assert.equal(bars[1].v.FCEV,2);assert.equal(bars[1].v.OTHERS,8);
 assert.equal(bars[2].v.FCEV,0);assert.equal(bars[2].v.OTHERS,10);
 bars.forEach(b=>assert.equal(Object.values(b.v).reduce((a,v)=>a+(v||0),0),b.tot));
});
test('unknown FCEV is not zero in selected values or export',()=>{
 const bars=r.bars('A',1,r.plan(['A']));r.setState({f:['FCEV']});
 assert.equal(r.displayValue(bars[0],'FCEV'),null);assert.equal(r.selectedTotal(bars[0]),null);
 assert.equal(r.completeSelection(bars[0]),false);assert.equal(r.completeSelection(bars[2]),true);
 r.render();const text=r.csvText();assert.match(text,/FCEV,SELECTED_TOTAL,TOTAL/);
 assert.doesNotMatch(text,/2000-01,2000-01/);assert.match(text,/,0,0,100/);
});
test('default All export leaves unknown optional cells blank',()=>{
 r.setState({f:null});r.render();const lines=r.csvText().split('\n').map(l=>l.split(','));
 const col=lines[0].indexOf('FCEV');assert(col>=0);assert.equal(lines[1][col],'');assert.equal(lines[2][col],'2');
});
test('TTM requires twelve confirmed months but legacy windows remain',()=>{
 reset({A:detailed([...Array(12).fill(null),...Array(12).fill(1)])});
 let bars=r.bars('A',12,r.plan(['A']));assert.equal(bars.length,13);
 assert.equal(bars[0].v.FCEV,null);assert.equal(bars[12].v.FCEV,12);
 r.setState({f:['FCEV']});assert.equal(bars.filter(r.completeSelection).length,1);
 r.setState({f:null});assert.equal(bars.filter(r.completeSelection).length,13);
});
test('optional annual resolution does not invent monthly counts',()=>{
 reset({A:detailed(Array(24).fill(1/12),12)});r.setState({f:['FCEV']});
 assert.equal(r.bars('A',1,r.plan(['A'])).filter(r.completeSelection).length,0);
 const bars=r.bars('A',12,r.plan(['A'])).filter(r.completeSelection);assert.equal(bars.length,2);
 bars.forEach(b=>assert(Math.abs(b.v.FCEV-1)<1e-9));
});
test('native coarse count is known only as its whole observation',()=>{
 const a=detailed([12,12,12],12);a.m=[24011,24023,24035];a.g=[12,12,12];a.step=12;
 a.t=[1200,1200,1200];a.b={BEV:[120,120,120],ICE:[960,960,960],OTHERS:[120,120,120]};
 reset({A:a});r.setState({f:['FCEV'],u:'abs'});const b=r.bars('A',1,r.plan(['A']))[0];
 assert.equal(b.span,12);assert.equal(b.v.FCEV,12);assert.equal(r.displayValue(b,'FCEV'),1);
});
test('mixed-coverage All aggregate keeps inclusive Other, not partial FCEV',()=>{
 reset({A:detailed([1,2,3]),B:series({BEV:10,ICE:80,OTHERS:10},100)});
 r.setState({c:['A','B']});const c=r.combined(['A','B'],1,r.plan(['A','B']));
 assert(c);c.list.forEach(b=>{assert.equal(b.v.FCEV,null);assert.equal(b.v.OTHERS,20);
  assert.equal(Object.values(b.v).reduce((a,v)=>a+(v||0),0),200);});
});
test('FCEV aggregate includes only confirmed fixed members and their TOTAL',()=>{
 r.setData({A:detailed([1,2,3]),B:series({BEV:10,ICE:80,OTHERS:10},100),C:detailed([2,3,4])});
 r.setState({c:['A','B','C'],f:['FCEV']});const c=r.combined(['A','B','C'],1,r.plan(['A','B','C']));
 assert.deepEqual(plain(c.members),['A','C']);assert.deepEqual(plain(c.excluded),['B']);
 assert.equal(c.list[0].v.FCEV,3);assert.equal(c.list[0].tot,200);
 assert.equal(r.combined(['A','B'],1,r.plan(['A','B'])),null);
});
test('Hero observed series is true BEV / original TOTAL, ignoring detail',()=>{
 const s=detailed(Array(24).fill(1));s.b.ICE=Array(24).fill(79);
 const observed=plain(ctx.ttmFromSeries(s));assert.equal(observed.length,13);
 observed.forEach(p=>assert.equal(p.y,.1));delete s.breakdown;
 assert.deepEqual(plain(ctx.ttmFromSeries(s)),observed);
});
test('loader rejects double-addends, misalignment and invalid detail',()=>{
 const s=detailed([1,2,3]);assert.equal(r.validateBreakdowns(s),s);
 for(const mutate of [x=>x.b.FCEV=[1,2,3],x=>x.breakdown.FCEV.v.pop(),
  x=>x.breakdown.FCEV.v[0]=11,x=>x.breakdown.FCEV.v[0]=-1,x=>x.breakdown.FCEV.g[0]=0]){
  const bad=JSON.parse(JSON.stringify(s));mutate(bad);assert.throws(()=>r.validateBreakdowns(bad));
 }
});

(async()=>{reset();r.setState({f:['BEV']});r.setView([{c:'A',l:[bar]}]);r.downloadCSV();
 assert.equal(await exportedBlob.text(),r.csvText());count++;console.log('ok  CSV download uses tested filtered content');
 console.log(count+' behavioral JavaScript tests passed');})().catch(e=>{console.error(e);process.exitCode=1;});
'''
result = subprocess.run(['node', '-e', 'const SOURCE=' + json.dumps(raw) + ';\n' + js],
                        text=True, check=False, timeout=30)
raise SystemExit(result.returncode)
