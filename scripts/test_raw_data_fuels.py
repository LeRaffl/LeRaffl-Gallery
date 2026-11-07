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
    availableFuels, plan, bars, combined, paintFuels, drawPlot, render, wire, csvText,
    downloadCSV, downloadPNG, svgToDataURL, stateHash, shareURL, readHash, writeHash,
    state:()=>S, setState:s=>Object.assign(S,s),
    setData:d=>{DATA=d;NAMES=Object.keys(d).sort();},
    setView:(v,sum=null)=>{VIEW=v;SUM=sum;}};
})();
'''
js = r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
let count=0;function test(name,fn){fn();count++;console.log('ok  '+name);}
const plain=x=>JSON.parse(JSON.stringify(x));
class Classes{
 constructor(){this.s=new Set();} add(x){this.s.add(x);} remove(x){this.s.delete(x);}
 contains(x){return this.s.has(x);} toggle(x,on){if(on)this.add(x);else this.remove(x);}
}
const downloads=[];let exportSvgs=[],imageOutcomes=[],nullCanvasBlob=false;
class ImageDouble{set src(_v){(imageOutcomes.shift() === false ? this.onerror : this.onload)();}}
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
 Image:ImageDouble,
 document:{getElementById:el,querySelectorAll:()=>exportSvgs,addEventListener(){},createElement:tag=>{
  if(tag==='canvas')return {getContext:()=>({fillRect(){},drawImage(){}}),toBlob:f=>f(nullCanvasBlob?null:new Blob(['PNG fixture']))};
  return new Element();}}};
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
test('All absolute axis uses the actual drawn sum even with a tolerated TOTAL difference',()=>{
 reset();const b={...bar,tot:1000,v:{BEV:20,ICE:1000}};assert.equal(r.axisMaximum([b]),1020);
 assert.equal(r.displayValue({...b,tot:1000},'BEV'),20);r.setState({u:'rel'});assert.equal(r.displayValue(b,'BEV'),.02);
});
test('CSV retains original fractional TOTAL precision, not a rounded denominator',()=>{
 reset();r.setView([{c:'A',l:[{...bar,tot:1000.125}]}]);assert.match(r.csvText(),/,1000\.125$/);
});
test('combined chart never adds a whole year to a single monthly observation',()=>{
 const yearly=series({BEV:120,ICE:1080},1200,{step:12,m:[24011,24023,24035],g:[12,12,12]});
 const monthly=series({BEV:10,ICE:90},100,{m:Array.from({length:36},(_,i)=>24000+i),g:Array(36).fill(1),
  t:Array(36).fill(100),b:{BEV:Array(36).fill(10),ICE:Array(36).fill(90)}});
 reset({A:yearly,B:monthly});r.setState({c:['A','B']});assert.equal(r.combined(['A','B'],1,r.plan(['A','B'])),null);
 const whole=r.combined(['A','B'],12,r.plan(['A','B']));assert(whole);assert.equal(whole.list[0].tot,2400);
});
test('time cutoff with an excluded member cannot crash on an empty combined list',()=>{
 const late=end=>series({BEV:10,ICE:990},1000,{m:[24000,24001,24002,end],g:[1,1,1,1],t:[1000,1000,1000,1000],
  b:{BEV:[10,10,10,10],ICE:[990,990,990,990]}});
 const data={A:late(24012),B:late(24013),C:series({BEV:10,ICE:990},1000,{m:[24008,24009,24014]})};
 reset(data);r.setState({c:['A','B','C'],t:1});r.render();assert.doesNotMatch(el('rdFoot').innerHTML,/undefined/);
});
function svgFixture(){return {outerHTML:'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 330"></svg>',getAttribute:()=> '0 0 600 330'};}
test('PNG export is all-or-nothing when an SVG fails, regardless of load order',()=>{
 for(const outcomes of [[false,true],[true,false]]){
  reset();exportSvgs=[svgFixture(),svgFixture()];imageOutcomes=[...outcomes];const before=downloads.length;
  r.downloadPNG();assert.equal(downloads.length,before);assert.match(el('rdFoot').textContent,/PNG export failed/);
 }
 exportSvgs=[];
});
test('PNG canvas failure is visible and never downloads a null/partial image',()=>{
 exportSvgs=[svgFixture()];imageOutcomes=[true];nullCanvasBlob=true;const before=downloads.length;
 r.downloadPNG();assert.equal(downloads.length,before);assert.match(el('rdFoot').textContent,/PNG export failed/);
 nullCanvasBlob=false;exportSvgs=[];
});
test('successful PNG export still downloads the filtered SVG composite',()=>{
 exportSvgs=[svgFixture()];imageOutcomes=[true];const before=downloads.length;r.downloadPNG();
 assert.equal(downloads.length,before+1);assert.match(downloads.at(-1).download,/rawdata_.*\.png$/);exportSvgs=[];
});

(async()=>{reset();r.setState({f:['BEV']});r.setView([{c:'A',l:[bar]}]);r.downloadCSV();
 assert.equal(await exportedBlob.text(),r.csvText());count++;console.log('ok  CSV download uses tested filtered content');
 console.log(count+' behavioral JavaScript tests passed');})().catch(e=>{console.error(e);process.exitCode=1;});
'''
result = subprocess.run(['node', '-e', 'const SOURCE=' + json.dumps(raw) + ';\n' + js],
                        text=True, check=False, timeout=30)
raise SystemExit(result.returncode)
