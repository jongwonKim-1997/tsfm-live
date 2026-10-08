import en from '../i18n/en.json';
import ko from '../i18n/ko.json';

const locale=document.documentElement.lang;
const words:Record<string,string>=locale==='ko'?ko:en;
const t=(key:string)=>words[key]||key;
const num=(v:any,d=1)=>v==null?'—':new Intl.NumberFormat(locale,{maximumFractionDigits:d}).format(v);
const pct=(v:any)=>v==null?'—':num(v*100)+'%';
const link=(p:string)=>(locale==='ko'?'/ko':'')+p;
const cell=(tag:string,value:any)=>{const node=document.createElement(tag);node.textContent=String(value??'—');return node;};
const api=async(path:string)=>{const r=await fetch('/api/v1/'+path+'.json');if(!r.ok)throw new Error('Data unavailable');return r.json();};
let currentWindow='90d';
let currentRegime='all';
let requestVersion=0;
let catalog:any;

async function updateRanking(){
  const version=++requestVersion;
  const table=document.querySelector('[data-role="leaderboard"]') as HTMLTableElement;
  if(!table)return;
  table.setAttribute('aria-busy','true');
  try{
    const [data,meta]=await Promise.all([api('leaderboard/'+currentWindow),catalog?Promise.resolve(catalog):api('meta')]);
    catalog=meta;
    if(version!==requestVersion)return;
    const names=Object.fromEntries(meta.entrants.map((m:any)=>[m.id,m.name]));
    const rows=currentRegime==='all'?data.entrants:data.regimes[currentRegime];
    const ciMin=Math.min(0,...rows.map((r:any)=>r.ci_low??0));
    const ciMax=Math.max(.05,...rows.map((r:any)=>r.ci_high??0));
    const pos=(value:number)=>(value-ciMin)/(ciMax-ciMin)*100;
    const body=table.tBodies[0];body.replaceChildren();
    for(const r of rows){
      const tr=document.createElement('tr');if(r.kind==='baseline')tr.className='baseline-row';
      tr.append(cell('td',['7d','30d'].includes(currentWindow)?'—':r.rank));
      const name=cell('th','');name.setAttribute('scope','row');const a=document.createElement('a');a.href=link('/models/'+r.id);a.textContent=names[r.id]||r.id;name.append(a);
      const badge=cell('small',t(r.kind)+(r.status==='ranked'?'':' · '+t('probation')));name.append(badge);tr.append(name);
      const skill=cell('td','');skill.append(cell('strong',pct(r.skill_overall)+(r.sig_vs_volnaive?' ✓':'')),cell('small',`${pct(r.ci_low)} … ${pct(r.ci_high)} · n=${r.n||r.paired_n_total||r.n_total||0}`));if(r.ci_low!=null){const bar=cell('span','');bar.className='ci-bar';bar.setAttribute('aria-hidden','true');bar.style.setProperty('--ci-start',pos(r.ci_low)+'%');bar.style.setProperty('--ci-end',pos(r.ci_high)+'%');bar.style.setProperty('--ci-zero',pos(0)+'%');bar.append(document.createElement('i'),document.createElement('b'));skill.insertBefore(bar,skill.lastChild);}
      skill.className='skill-cell';tr.append(skill);
      tr.append(cell('td',r.tier),cell('td',r.rank_change),cell('td',pct(r.win_rate??r.win_rate_overall)));
      const hit=cell('td',pct(r.hit_rate));hit.append(cell('small',`n=${r.hit_n||0}`));tr.append(hit);
      tr.append(cell('td',pct(r.cov80)),cell('td',pct(r.cov95)),cell('td',r.live_days),cell('td',`${r.best_indicator||'—'} / ${r.worst_indicator||'—'}`));body.append(tr);
    }
    const note=document.querySelector('#small-window-note') as HTMLElement;
    if(note)note.hidden=!['7d','30d'].includes(currentWindow);
  }catch{table.setAttribute('data-error','true');}
  finally{if(version===requestVersion)table.removeAttribute('aria-busy');}
}
document.querySelectorAll<HTMLButtonElement>('[data-window]').forEach(button=>button.addEventListener('click',()=>{
  currentWindow=button.dataset.window!;
  document.querySelectorAll<HTMLButtonElement>('[data-window]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  updateRanking();
}));
document.querySelector<HTMLSelectElement>('#regime-select')?.addEventListener('change',event=>{
  currentRegime=(event.target as HTMLSelectElement).value;updateRanking();
});
document.querySelectorAll<HTMLButtonElement>('[data-view]').forEach(button=>button.addEventListener('click',()=>{
  document.querySelector('#indicator-grid')?.classList.toggle('list-view',button.dataset.view==='list');
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
}));
document.querySelectorAll<HTMLButtonElement>('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText(button.dataset.copy!);button.setAttribute('aria-label',`${t('copied')} · ${button.dataset.copy!.slice(0,14)}…`);button.querySelector('span')!.textContent='✓';}catch{}
}));
document.querySelector<HTMLSelectElement>('#detail-window')?.addEventListener('change',async event=>{
  const select=event.target as HTMLSelectElement;
  const body=document.querySelector('#detail-table tbody')!;
  const data=await api(select.dataset.section+'/'+select.dataset.id);
  const meta=catalog||await api('meta');catalog=meta;
  const names=Object.fromEntries([...meta.indicators,...meta.entrants].map((x:any)=>[x.id,x.name]));
  body.replaceChildren();
  for(const [id,r] of Object.entries(data.windows[select.value]) as [string,any][]){
    const tr=document.createElement('tr');const name=cell('th','');name.setAttribute('scope','row');const a=document.createElement('a');a.href=link('/'+(select.dataset.section==='models'?'indicators':'models')+'/'+id);a.textContent=names[id];name.append(a);tr.append(name);
    tr.append(cell('td',pct(r?.skill_crps)),cell('td',num(r?.crps_mean,4)),cell('td',pct(r?.hit_rate)),cell('td',pct(r?.cov80)),cell('td',pct(r?.cov95)),cell('td',r?.n??data.window_counts?.[select.value]?.[id]?.n??0));body.append(tr);
  }
});

document.querySelectorAll<HTMLSelectElement>('[data-interval-select]').forEach(select=>select.addEventListener('change',()=>{
  select.closest('.interval-history')?.querySelectorAll<HTMLElement>('[data-interval-panel]').forEach(panel=>{panel.hidden=panel.dataset.intervalPanel!==select.value;});
}));
