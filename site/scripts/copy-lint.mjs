import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';

export const banned = ['our forecast','our prediction','prediction service','recommend','buy','sell','long','short','target price','outlook','signal','alpha','profit','returns you can expect'];
export function violations(text){
  return banned.filter(phrase=>new RegExp('\\b'+phrase.replaceAll(' ','\\s+')+'(?:ation|s)?\\b','i').test(text));
}
// Reviewed exact UTF-8 disclaimers, mirrored in docs/compliance.md. Changing
// either wording requires a visible update to this allowlist and the document.
export const disclaimerHashes = Object.freeze({
  en:'ecb9400665ed9e6c949d7b4b3cdc03dfe01ffa467d328cfcc165ce761a767f1d',
  ko:'4f5ab2cee38e703dd35726e1649dc5a464150fa6ee7008231a538e2fdbe3ea3b',
});
export function validDisclaimer(locale,text){
  return typeof text==='string' && disclaimerHashes[locale] === createHash('sha256').update(text,'utf8').digest('hex');
}
export function markdownCopy(text){
  // Keep link labels and visible examples; destinations are references, not copy.
  return text.replace(/(!?\[[^\]]*\])\([^)]*\)/g,'$1').replace(/<https?:\/\/[^>]+>/g,'');
}
const repoRoot=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
export function checkCopy(directory='src'){
  const en=JSON.parse(fs.readFileSync(path.join(directory,'i18n/en.json'),'utf8'));
  const ko=JSON.parse(fs.readFileSync(path.join(directory,'i18n/ko.json'),'utf8'));
  const errors=[];
  if(JSON.stringify(Object.keys(en).sort())!==JSON.stringify(Object.keys(ko).sort()))errors.push('Locale keys differ');
  // Only the exact reviewed disclaimer text is exempt, never arbitrary text
  // placed under a convenient key. Missing or modified disclaimers fail closed.
  for(const [locale,strings] of Object.entries({en,ko})){
    if(!validDisclaimer(locale,strings.disclaimer))errors.push(`${locale}.disclaimer: exact reviewed text required`);
  }
  for(const [locale,strings] of Object.entries({en,ko}))for(const [key,value] of Object.entries(strings)){
    if(key==='disclaimer'&&validDisclaimer(locale,value))continue;
    for(const phrase of violations(value))errors.push(`${locale}.${key}: ${phrase}`);
  }
  const walk=dir=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(d=>d.isDirectory()?walk(path.join(dir,d.name)):[path.join(dir,d.name)]);
  for(const file of walk(directory).filter(f=>/\.(astro|ts|mjs|css)$/.test(f))){
    const source=fs.readFileSync(file,'utf8');
    // Technical identifiers are not rendered product copy. Check literal text nodes
    // and human strings; word boundaries do not match e.g. strokeWidth or longitude.
    for(const phrase of violations(source.replace(/\/\*[\s\S]*?\*\//g,'').replace(/^\s*\/\/.*$/gm,'')))errors.push(`${file}: ${phrase}`);
  }
  for(const relative of ['docs/methodology.md','docs/methodology.ko.md']){
    const file=path.join(repoRoot,relative);
    for(const phrase of violations(markdownCopy(fs.readFileSync(file,'utf8'))))errors.push(`${relative}: ${phrase}`);
  }
  const cards=fs.readFileSync(path.join(repoRoot,'site/scripts/cards.mjs'),'utf8');
  for(const phrase of violations(cards.replace(/\/\*[\s\S]*?\*\//g,'').replace(/^\s*\/\/.*$/gm,'')))errors.push(`scripts/cards.mjs: ${phrase}`);
  if(errors.length)throw new Error('Copy checks failed:\n'+errors.join('\n'));
  return true;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  checkCopy();console.log('Copy and locale checks passed');
}
