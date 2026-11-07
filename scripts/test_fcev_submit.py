#!/usr/bin/env python3
"""Exercise the actual Worker CSV/upsert and submission validator, offline."""
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
js=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('index.html','utf8');
let calls=0;const c=vm.createContext({Response,console,fetch:()=>{throw Error('Network forbidden')},atob,btoa,TextDecoder});
vm.runInContext(fs.readFileSync('worker/index.js','utf8').replace('export default {','const worker = {')+
 ';globalThis.w={upsertRows,csvRecords,FUEL_ORDER,handleSubmission,decodeGitHubCsv};',c);
const w=c.w,plain=x=>JSON.parse(JSON.stringify(x));let count=0;
function test(name,f){f();count++;console.log('ok '+name);}
const header=['period','time_interval','variant','source','BEV','OTHERS','TOTAL','FCEV','notes'];
const original=header.join(',')+'\r\n2026-01,monthly,Whole,"source, x",10,8,100,2,"note, ""quote""\nline"\r\n';
function row(fuels={},period='2026-01'){return {period,time_interval:'monthly',fuels:{BEV:11,OTHERS:8,TOTAL:100,...fuels},notes:'new, "note"\nline'};}
function record(text,index=1){const records=w.csvRecords(text),cols=records[0].fields;return Object.fromEntries(records[index].fields.map((v,i)=>[cols[i],v]));}
test('frontend and Worker use one matching fuel registry including FCEV',()=>{
 const list=html.match(/const SD_FUEL_ORDER = (\[[^;]+\]);/)[1];assert.deepEqual(plain(vm.runInNewContext(list)),plain(w.FUEL_ORDER));
 assert(html.includes("const cats = SD_FUEL_ORDER.filter(k=>k !== 'TOTAL')"));
});
test('omitted optional value survives correction with quoted multiline fields',()=>{
 const out=w.upsertRows(original,'Whole','source, corrected',[row()]);const r=record(out.newCsv);
 assert.equal(r.FCEV,'2');assert.equal(r.BEV,'11');assert.equal(r.source,'source, corrected');assert.equal(r.notes,'new, "note"\nline');
 assert.equal(w.csvRecords(out.newCsv).length,2);assert.equal(out.summary.replaced,1);
});
test('zero is measured, null is deliberate unknown, absent new row is blank',()=>{
 assert.equal(record(w.upsertRows(original,'Whole','s',[row({FCEV:0})]).newCsv).FCEV,'0');
 assert.equal(record(w.upsertRows(original,'Whole','s',[row({FCEV:null})]).newCsv).FCEV,'');
 assert.equal(record(w.upsertRows(original,'Whole','s',[row({},'2026-02')]).newCsv,2).FCEV,'');
});
test('adding optional schema pads history without moving quoted notes',()=>{
 const old='period,time_interval,variant,source,BEV,TOTAL,notes\n2026-01,monthly,Whole,"s, x",10,100,"n, ""q""\nnext"\n';
 const out=w.upsertRows(old,'Whole','s',[row({FCEV:0},'2026-02')]).newCsv;
 assert.equal(record(out).FCEV,'');assert.equal(record(out).notes,'n, "q"\nnext');assert.equal(record(out,2).FCEV,'0');
});
test('untouched record tokens and unknown optional columns pass through',()=>{
 const csv=original.replace('FCEV,notes','FCEV,EXTRA,notes').replace('100,2,','100,2,1.00e2,');
 const out=w.upsertRows(csv,'Whole','s',[row({},'2026-02')]).newCsv;
 assert.equal(record(out).EXTRA,'1.00e2');assert.equal(record(out).FCEV,'2');assert(out.includes('100,2,1.00e2,'));
});
test('new file canonical order separates FCEV without activating it by default',()=>{
 const out=w.upsertRows(null,'Whole','s',[row({FCEV:1})]).newCsv;
 assert(out.startsWith('period,time_interval,variant,source,BEV,FCEV,OTHERS,TOTAL,notes\n'));
 assert(!w.upsertRows(null,'Whole','s',[row()]).newCsv.split('\n')[0].includes('FCEV'));
});
test('existing UTF-8 provenance is decoded once, not mojibake/double encoded',()=>{
 const text=original.replace('source, x','JADA 日本, H₂').replace('note,','注記,');
 assert.equal(w.decodeGitHubCsv(Buffer.from(text,'utf8').toString('base64')),text);
 assert.throws(()=>w.decodeGitHubCsv('/w==')); // invalid UTF-8 is not rewritten
});
test('untouched complete records retain CRLF, numeric tokens and final-newline state',()=>{
 for(const eol of ['\n','\r\n','\r'])for(const final of [true,false]){
  const text=header.join(',')+eol+'2026-01,monthly,Whole,"日本, H₂",1.00e1,8.000,100.00,2,"note"'+(final?eol:'');
  const out=w.upsertRows(text,'Whole','s',[row({},'2026-02')]).newCsv;
  assert(out.startsWith(text+(final?'':eol)));assert.equal(/[\r\n]$/.test(out),final);
 }
});
test('schema expansion retains every historical field token including quoted numbers',()=>{
 const old='period,time_interval,variant,source,BEV,TOTAL,notes\r\n2026-01,monthly,Whole,"日本, H₂","1.00e1",100.00,"note, ""quote""\nline"';
 const out=w.upsertRows(old,'Whole','s',[{period:'2026-02',time_interval:'monthly',fuels:{BEV:11,FCEV:0,TOTAL:100},notes:''}]).newCsv;
 assert(out.includes('"日本, H₂","1.00e1",100.00,,"note, ""quote""\nline"\r\n'));
 assert(!out.endsWith('\n'));
});
test('unknown optional columns survive corrections, not just untouched rows',()=>{
 const text=original.replace('FCEV,notes','FCEV,EXTRA,notes').replace('100,2,','100,2,"001.00, keep",');
 const out=w.upsertRows(text,'Whole','s',[row()]).newCsv;assert.equal(record(out).EXTRA,'001.00, keep');
});
test('effective preserved FCEV and overlap cannot evade original TOTAL validation',()=>{
 const text='period,time_interval,variant,source,BEV,FCEV,ICE,OTHERS,TOTAL,notes\n2026-01,monthly,Whole,s,10,2,80,8,100,\n';
 for(const fuels of [{BEV:99,ICE:0,OTHERS:0,TOTAL:100},{BEV:10,FCEV:1,ICE:80,OTHERS:10,TOTAL:100}])
  assert.throws(()=>w.upsertRows(text,'Whole','s',[row(fuels)]),/original TOTAL/);
 assert.throws(()=>w.upsertRows(text,'Whole','s',[row(),row()]),/Duplicate submitted/);
 assert.throws(()=>w.upsertRows(text+text.split('\n')[1]+'\n','Whole','s',[row()]),/Duplicate existing/);
});
(async()=>{
 for(const f of [{FCEV:-1},{FCEV:'NaN'},{FCEV:'Infinity'},{FCEV:'bad'},{FCEV:true},{FCEV:[]},{HICEV:1},{FCEV:95}]){
  const req={headers:new Headers(),json:async()=>({country:'fixture',rows:[row(f)]})};
  assert.equal((await w.handleSubmission(req,{},{})).status,400);
 }
 const effective='period,time_interval,variant,source,BEV,FCEV,ICE,OTHERS,TOTAL,notes\n2026-01,monthly,Whole,"日本, H₂",10,2,80,8,100,\n';
  c.fixtureContent=Buffer.from(effective,'utf8').toString('base64');
 vm.runInContext(`ghFetch=async(path,token,opts={})=>{
   if(opts.method && opts.method!=='GET')throw Error('MUTATION FORBIDDEN');
   return new Response(JSON.stringify({sha:'fixture',content:globalThis.fixtureContent}),{status:200});
 };`,c);
 const invalid={headers:new Headers(),json:async()=>({country:'fixture',rows:[row({BEV:99,ICE:0,OTHERS:0})]})};
 const bad=await w.handleSubmission(invalid,{},{});assert.equal(bad.status,400);assert.match(await bad.text(),/original TOTAL/);
 const tiny={headers:new Headers(),json:async()=>({country:'fixture',rows:[row({BEV:100,FCEV:.1,OTHERS:0})]})};
 assert.equal((await w.handleSubmission(tiny,{},{})).status,400);
 c.fixtureContent='/w==';assert.equal((await w.handleSubmission({headers:new Headers(),json:async()=>({country:'fixture',rows:[row()]})},{},{})).status,502);
 // Stop after validation/read; no GitHub writes even in mocks. Inspect the
 // clean fuels delivered to upsert, including whitespace/blank preservation.
 vm.runInContext(`ghFetch=async()=>new Response('{}',{status:404});
   upsertRows=(csv,v,s,rows)=>{globalThis.cleaned=rows;throw Error('STOP AFTER VALIDATION')};`,c);
 for(const value of ['', ' ',null,0,1]){
  const req={headers:new Headers(),json:async()=>({country:'fixture',rows:[row({FCEV:value})]})};
  assert.equal((await w.handleSubmission(req,{},{})).status,502);
  const fuel=c.cleaned[0].fuels;
  assert.equal(fuel.FCEV,(typeof value==='string')?undefined:value);
 }
 console.log(`${count} Worker tests + effective/blank/error validator cases passed`);
})().catch(e=>{console.error(e);process.exit(1)});
'''
result=subprocess.run(['node','-e',js],cwd=root)
sys.exit(result.returncode)
