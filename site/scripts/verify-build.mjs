import fs from 'node:fs';
import path from 'node:path';
import {JSDOM} from 'jsdom';
const walk=dir=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(d=>d.isDirectory()?walk(path.join(dir,d.name)):[path.join(dir,d.name)]);
const dist=process.env.TSFM_SITE_OUTDIR||'dist';
const files=walk(dist).filter(f=>f.endsWith('.html'));
const errors=[];
for(const file of files){
  const doc=new JSDOM(fs.readFileSync(file,'utf8')).window.document;
  if(!doc.querySelector('h1'))errors.push(`${file}: missing main heading`);
  if(!doc.querySelector('meta[property="og:image"]'))errors.push(`${file}: missing social image`);
  if(!doc.querySelector('.disclaimer'))errors.push(`${file}: missing disclaimer`);
  for(const link of doc.querySelectorAll('a[href^="/"]')){
    const href=link.getAttribute('href').split('#')[0].split('?')[0];
    if(!href||href==='/'||href.startsWith('//'))continue;
    const target=path.join(dist,href);
    if(!fs.existsSync(target)&&!fs.existsSync(path.join(target,'index.html')))errors.push(`${file}: broken ${href}`);
  }
  const image=doc.querySelector('meta[property="og:image"]')?.content;
  if(image&&!fs.existsSync(path.join(dist,new URL(image).pathname)))errors.push(`${file}: missing image file`);
}
if(errors.length)throw new Error(errors.slice(0,40).join('\n'));
const origin=process.env.TSFM_PUBLIC_ORIGIN||'http://localhost:4321';
const urls=files.filter(f=>!f.includes('404')).map(f=>origin+'/'+path.relative(dist,f).replaceAll('\\','/').replace(/index.html$/,''));
fs.writeFileSync(path.join(dist,'sitemap.xml'),`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls.map(url=>`<url><loc>${url}</loc></url>`).join('')}</urlset>`);
console.log(`Verified ${files.length} pages, links, disclaimers and social images`);
