#!/usr/bin/env python3
"""Exercise the actual Worker CSV/upsert and submission validator, offline."""
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
js=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('index.html','utf8');
let calls=0;const c=vm.createContext({Response,console,fetch:()=>{throw Error('Network forbidden')},atob,btoa});
vm.runInContext(fs.readFileSync('worker/index.js','utf8').replace('export default {','const worker = {')+
 ';globalThis.w={upsertRows,csvRecords,FUEL_ORDER,handleSubmission};',c);
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
(async()=>{
 for(const f of [{FCEV:-1},{FCEV:'NaN'},{FCEV:'Infinity'},{FCEV:'bad'},{HICEV:1},{FCEV:95}]){
  const req={headers:new Headers(),json:async()=>({country:'fixture',rows:[row(f)]})};
  assert.equal((await w.handleSubmission(req,{},{})).status,400);
 }
 // Stop after validation/read; no GitHub writes even in mocks. Inspect the
 // clean fuels delivered to upsert, including whitespace/blank preservation.
 vm.runInContext(`ghFetch=async()=>new Response('{}',{status:404});
   upsertRows=(csv,v,s,rows)=>{globalThis.cleaned=rows;throw Error('STOP AFTER VALIDATION')};`,c);
 for(const value of ['', ' ',null,0,1]){
  const req={headers:new Headers(),json:async()=>({country:'fixture',rows:[row({FCEV:value})]})};
  await assert.rejects(w.handleSubmission(req,{},{}),/STOP AFTER VALIDATION/);
  const fuel=c.cleaned[0].fuels;
  assert.equal(fuel.FCEV,(typeof value==='string')?undefined:value);
 }
 console.log(`${count} Worker tests + 11 validator cases passed`);
})().catch(e=>{console.error(e);process.exit(1)});
'''
result=subprocess.run(['node','-e',js],cwd=root)
sys.exit(result.returncode)
