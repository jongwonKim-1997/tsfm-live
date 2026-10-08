import fs from 'node:fs';
import path from 'node:path';
import {Resvg} from '@resvg/resvg-js';

const publicDir=process.env.TSFM_PUBLIC_DIR||'public';
const apiDir=process.env.TSFM_API_DIR||path.join(publicDir,'api/v1');
const read=name=>JSON.parse(fs.readFileSync(path.join(apiDir,name+'.json'),'utf8'));
const latest=read('latest');
const board=read('leaderboard/90d');
const pi=read('predictability');
const meta=read('meta');
const day=latest.run_date||'bootstrap';
const dir=path.join(publicDir,'cards',day);fs.mkdirSync(dir,{recursive:true});
const esc=text=>String(text).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const name=id=>[...meta.entrants,...meta.indicators].find(x=>x.id===id)?.name||id;
const percent=n=>n==null?'—':`${(n*100).toFixed(1)}%`;
const labels={board:'Model outputs',leaderboard:'Model performance',predictability:'Indicator predictability',scorecard:'Model scorecard'};
for(const kind of Object.keys(labels))for(const square of [false,true]){
  const width=square?1080:1200,height=square?1080:630;
  const title=(meta.fixture?'SYNTHETIC FIXTURE · ':'')+labels[kind]+(latest.run_date?' · '+latest.run_date:'');
  let lines=[];
  if(!latest.run_date){lines=['Awaiting the first public lock-in','No live scores. No manufactured history.','Prospective evaluation begins with a verifiable record.'];}
  else if(kind==='leaderboard')lines=board.entrants.slice(0,5).map(r=>`${r.rank??'Unranked'}  ${name(r.id)}   ${percent(r.skill_overall)}   [${percent(r.ci_low)}, ${percent(r.ci_high)}] n=${r.n??r.n_total??0}`);
  else if(kind==='predictability')lines=pi.indicators.slice(0,5).map(r=>`${name(r.id||r.indicator_id)}   PI ${r.PI==null?'—':r.PI.toFixed(1)}   ${r.label}   n=${r.n}`);
  else if(kind==='board')lines=latest.records.filter(r=>r.status==='ok').slice(0,5).map(r=>`${name(r.indicator_id)} · ${name(r.entrant_id)}   q50 ${r.q['0.5'].toFixed(3)}  [${r.q['0.1'].toFixed(3)}, ${r.q['0.9'].toFixed(3)}]`);
  else lines=['See the dated scorecards in the public ledger.','Every result refers to a locked model output.'];
  if(!lines.length)lines=['No eligible model outputs for this session.'];
  const body=lines.map((line,index)=>`<text x="76" y="${250+index*56}" font-size="${index===0&&!latest.run_date?31:23}" fill="${index===0?'#edf3ff':'#bac8de'}">${esc(line)}</text>`).join('');
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#090f1b"/><path d="M${width-180} 80v150m36-175v200m36-170v145m36-110v80" stroke="#659aff" stroke-width="12" opacity=".36"/><text x="76" y="76" font-family="Arial,sans-serif" font-size="27" fill="#8db8ff">TSFM Live</text><text x="76" y="148" font-family="Arial,sans-serif" font-size="43" fill="#fff">${esc(title)}</text><g font-family="Arial,sans-serif">${body}</g><path d="M76 ${height-110}H${width-76}" stroke="#2b3d59"/><text x="76" y="${height-72}" font-family="Arial,sans-serif" font-size="17" fill="#adbeda">Research &amp; benchmarking only · CRPS vs volatility-adjusted random walk</text><text x="76" y="${height-40}" font-family="monospace" font-size="14" fill="#93a8c9">${latest.hash?'SHA-256 '+esc(latest.hash):'Shadow period · no live observations published'}</text></svg>`;
  const png=new Resvg(svg,{font:{loadSystemFonts:true,defaultFontFamily:'Arial'}}).render().asPng();
  fs.writeFileSync(path.join(dir,kind+(square?'-square':'')+'.png'),png);
}
console.log(`Generated 8 evidence-based cards in ${dir}`);
