// Prints the source of named top-level declarations in index.html so tests
// can run the in-page logic under node without a browser.
// usage: node scripts/js_extract.js index.html name1 [name2 ...]
const fs=require('fs');const src=fs.readFileSync(process.argv[2],'utf8');
function grab(name){
  const re=new RegExp('^(?:async )?function '+name+'\\s*\\(|^(?:const|let|var) '+name+'\\b','m');
  const m=re.exec(src); if(!m) throw new Error('missing '+name);
  const i=m.index;
  if(!/^(async )?function/.test(src.slice(i,i+15))){
    const eol = src.indexOf('\n', i), line = src.slice(i, eol).replace(/\/\/.*$/, '').trimEnd();
    if (!/[{\[]$/.test(line)) return src.slice(i, eol);
    // multi-line object / array literal: match brackets to the closing one
    let d = 0;
    for (let j = i + line.length - 1; j < src.length; j++){
      if (src[j] === '{' || src[j] === '[') d++;
      else if ((src[j] === '}' || src[j] === ']') && !--d) return src.slice(i, src.indexOf('\n', j));
    }
  }
  let j=src.indexOf('{',src.indexOf(')',i)), d=0;
  for(;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(i,j+1);} }
}
console.log(process.argv.slice(3).map(grab).join('\n'));
