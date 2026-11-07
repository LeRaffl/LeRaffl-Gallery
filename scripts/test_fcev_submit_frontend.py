#!/usr/bin/env python3
"""Actual Submit JS: quoted schemas, async races and unknown-vs-zero sums."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
html = (root / 'index.html').read_text(encoding='utf-8')
start = html.index('const SD_FUEL_ORDER =')
end = html.index('// English month/quarter labels', start)
source = html[start:end]
start_sum = html.index('function sdUpdateSumcheck(node)')
source += html[start_sum:html.index('\n}\n', start_sum)+3]
source += '\nglobalThis.fe={sdCsvRecords,sdOnCountryChange,sdUpdateSumcheck,state:SD_STATE};'
js = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map();function el(id){if(!elements.has(id))elements.set(id,{value:'',children:[],appendChild(x){this.children.push(x)}});return elements.get(id)}
let responders=[],added=0;
const ctx={console,document:{getElementById:el,createElement:()=>({dataset:{}})},
 fetch:()=>new Promise(resolve=>responders.push(resolve)),sdMsg(){},sdAddRow(){added++},fmtInt:n=>String(n)};
vm.createContext(ctx);vm.runInContext(SOURCE,ctx);const f=ctx.fe;
const plain=x=>JSON.parse(JSON.stringify(x));let count=0;
const csv='"period",time_interval,variant,source,BEV,FCEV,TOTAL,notes\r\n2026-12,monthly,Whole,"日本, <img src=x>",10,,100,"note, ""quote""\r\nnext"';
function respond(i,text){responders[i]({ok:true,text:async()=>text})}
function sumNode(fuels){const status={},inputs=Object.entries(fuels).map(([fuel,value])=>({dataset:{fuel},value:String(value)}));return {
 status,querySelectorAll:()=>inputs,querySelector:s=>s==='[data-sumcheck]'?status:inputs.find(i=>i.dataset.fuel==='FCEV')};}
(async()=>{
 const parsed=f.sdCsvRecords(csv);assert.equal(parsed.length,2);assert.equal(parsed[0][0],'period');
 assert.equal(parsed[1][3],'日本, <img src=x>');assert.equal(parsed[1][7],'note, "quote"\r\nnext');
 assert.throws(()=>f.sdCsvRecords('a,"unclosed'));count++;
 el('sdCountry').value='Japan';el('sdVariant').value='Whole';const first=f.sdOnCountryChange();assert(el('sdSubmit').disabled);
 respond(0,csv);await first;assert.equal(f.state.nextYear,2027);assert.equal(f.state.nextMonth,1);
 assert(plain(f.state.countryCols).includes('FCEV'));assert.equal(el('sdSourceHint').children.at(-1).textContent,'日本, <img src=x>');
 assert.equal(el('sdSubmit').disabled,false);count++;
 responders=[];added=0;const slow=f.sdOnCountryChange();el('sdCountry').value='South Korea';el('sdVariant').value='Vans';const fast=f.sdOnCountryChange();
 respond(1,'period,time_interval,variant,source,BEV,TOTAL,notes\n2025-04,monthly,Vans,fast schema,2,10,\n');await fast;
 assert.equal(f.state.lastSource,'fast schema');assert(!plain(f.state.countryCols).includes('FCEV'));
 respond(0,csv);await slow;assert.equal(f.state.lastSource,'fast schema');assert.equal(added,1);assert.equal(f.state.nextMonth,5);count++;
 let n=sumNode({BEV:100,FCEV:.1,TOTAL:100});f.sdUpdateSumcheck(n);assert.match(n.status.className,/bad/);
 n=sumNode({BEV:10,FCEV:0,ICE:90,TOTAL:100});f.sdUpdateSumcheck(n);assert.match(n.status.className,/good/);
 n=sumNode({BEV:10,FCEV:'',ICE:90,TOTAL:100});f.sdUpdateSumcheck(n);assert.doesNotMatch(n.status.className,/good/);assert.match(n.status.textContent,/retained on corrections/);count++;
 console.log(count+' Submit frontend behavioral groups passed (no network)');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
result = subprocess.run(['node', '-e', 'const SOURCE='+json.dumps(source)+';\n'+js], cwd=root, timeout=30)
raise SystemExit(result.returncode)
