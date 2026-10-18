import {escapeHTML as esc} from './forecast-view.mjs';

const palette=['#53a6ff','#5ce0cc'];
const text={ko:{title:'어제의 예측을 확인하고, 내일을 봅니다.',kicker:'DAILY FORECAST · LOCAL GPU',actual:'실제 관측값',previous:'어제 발행한 예측',next:'오늘 발행한 예측',today:'오늘 실제값',tomorrow:'내일 / 다음 발표일',pending:'아직 발표되지 않았습니다',closed:'휴장 · 발표 없음',noPrior:'어제 발행된 예측이 없습니다. 운영 시작 후 쌓입니다.',history:'실제값 기간',seven:'최근 7일',month:'최근 30일',basis:'기준일',updated:'최근 갱신',model:'모델',notReady:'예측 준비 중',stale:'갱신이 지연되었습니다. 아래 날짜를 확인하세요.',note:'지표 자신의 일별 과거값만 사용한 zero-shot 예측입니다. 실제값과 모델 출력을 구분하며, 과거 발행 예측은 보존합니다.',dates:'날짜는 각 지표의 원천 관측일입니다. 발행일과 실행 일정은 한국시간입니다. 주말·휴일은 다음 발표일로 이동합니다.',licence:'출처와 이용 조건',pendingIndex:'주가지수 연결 대기',indexNote:'KOSPI · S&P 500 · NASDAQ — 상업적 공개 표시 권한이 확인된 데이터 계약이 필요합니다.',interval:'음영·세로선: 모델의 80% 주변 예측 구간. 정확도 보장이 아닙니다.',noData:'현재 수집된 데이터가 없습니다.',all:'모든 모델',one:'단일 지표의 과거만',comparison:'어제 발행 → 오늘 결과 / 오늘 발행 → 내일 결과'},en:{title:'Check yesterday. See tomorrow.',kicker:'DAILY FORECAST · LOCAL GPU',actual:'Observed actuals',previous:'Issued yesterday',next:'Issued today',today:'Today’s actual',tomorrow:'Tomorrow / next release',pending:'Not yet released',closed:'Closed / no release',noPrior:'No forecast was issued yesterday. History accumulates from launch.',history:'Actuals window',seven:'Last 7 days',month:'Last 30 days',basis:'As of',updated:'Last refreshed',model:'Model',notReady:'Forecast pending',stale:'Update delayed. Check the dates below.',note:'Zero-shot forecasts use only each indicator’s own daily history. Actuals and model outputs are separate; previously issued forecasts are preserved.',dates:'Dates refer to source observation days. Issue dates and schedules use Korea time. Weekends and holidays move to the next release.',licence:'Sources and reuse terms',pendingIndex:'Equity indices pending',indexNote:'KOSPI · S&P 500 · NASDAQ — a verified commercial public-display data licence is required.',interval:'Shading / whiskers: model 80% marginal intervals, not an accuracy guarantee.',noData:'No collected observations available.',all:'All models',one:'Own history only',comparison:'Issued yesterday → today / issued today → tomorrow'}};

export function validDaily(data){return data?.schema_version==='daily-public-v1'&&data.frequency==='1d'&&Array.isArray(data.indicators)&&Number.isFinite(Date.parse(data.generated_ts_utc));}
const fmt=(n,unit)=>Number.isFinite(n)?new Intl.NumberFormat('en-US',{maximumFractionDigits:unit==='%'?3:4}).format(n):'—';
const stamp=value=>value?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value))+' KST':'—';

export function dailyChart(row,data,{days=7,model='all',locale='ko'}={}){
  const w=text[locale]||text.en,W=940,H=360,L=76,R=24,T=26,B=52;
  const since=Date.parse(data.date+'T00:00:00Z')-(days-1)*86400000;
  const actuals=(row.history||[]).filter(p=>Date.parse(p.date)>=since);
  const today=(row.forecasts||[]).filter(f=>model==='all'||f.model_id===model);
  const previous=(row.previous_forecasts||[]).filter(f=>model==='all'||f.model_id===model);
  const forecasts=[...today,...previous];
  const dates=[...actuals.map(p=>p.date),data.date,...forecasts.flatMap(f=>[f.anchor.date,...f.points.map(p=>p.date)])].sort();
  if(!actuals.length&&!forecasts.length)return `<p class="daily-empty">${esc(w.noData)}</p>`;
  const start=Math.max(since,Date.parse(dates[0])),end=Math.max(start+86400000,Date.parse(dates.at(-1)));
  const values=[...actuals.map(p=>p.value),...forecasts.flatMap(f=>[f.anchor.value,...f.points.flatMap(p=>[p.lower,p.upper])])].filter(Number.isFinite);
  let low=Math.min(...values),high=Math.max(...values);const pad=Math.max((high-low)*.15,Math.abs(high)*.0006,.001);low-=pad;high+=pad;
  const x=d=>L+(Date.parse(d)-start)/(end-start)*(W-L-R), y=v=>T+(high-v)/(high-low)*(H-T-B);
  const path=points=>points.map((p,i)=>`${i?'L':'M'}${x(p.date).toFixed(2)},${y(p.value).toFixed(2)}`).join(' ');
  const dots=(points,color)=>points.map(p=>`<circle cx="${x(p.date)}" cy="${y(p.value)}" r="4" fill="${color}"><title>${esc(p.date)} · ${fmt(p.value,row.unit)} ${esc(row.unit)}</title></circle>`).join('');
  const grid=Array.from({length:5},(_,i)=>{const v=low+(high-low)*i/4;return `<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="#263348"/><text x="${L-12}" y="${y(v)+4}" text-anchor="end" fill="#9aaac0" font-size="12">${fmt(v,row.unit)}</text>`;}).join('');
  let marks='';
  for(const [index,f] of today.entries()){
    const c=palette[f.model_id==='chronos-bolt-base'?1:0]||palette[index%2];
    const points=[{date:f.anchor.date,value:f.anchor.value},...f.points.map(p=>({date:p.date,value:p.median}))].filter(p=>Date.parse(p.date)>=start);
    const band=[...f.points.map(p=>({date:p.date,value:p.lower})),...f.points.slice().reverse().map(p=>({date:p.date,value:p.upper}))];
    marks+=`<path d="${path(band)} Z" fill="${c}" opacity=".13"/><path d="${path(points)}" fill="none" stroke="${c}" stroke-width="3"/>${dots(points,c)}`;
    if(f.points.length===1){const p=f.points[0],px=x(p.date),lo=y(p.lower),hi=y(p.upper);marks+=`<path d="M${px},${lo} V${hi} M${px-5},${lo} h10 M${px-5},${hi} h10" fill="none" stroke="${c}" stroke-width="2" opacity=".7"><title>80%: ${fmt(p.lower,row.unit)} – ${fmt(p.upper,row.unit)}</title></path>`;}
  }
  for(const f of previous){const points=[{date:f.anchor.date,value:f.anchor.value},...f.points.map(p=>({date:p.date,value:p.median}))].filter(p=>Date.parse(p.date)>=start);marks+=`<path d="${path(points)}" fill="none" stroke="#f7b955" stroke-width="2" stroke-dasharray="7 5"/>${dots(points,'#f7b955')}`;}
  const labels=Array.from({length:5},(_,i)=>new Date(start+(end-start)*i/4).toISOString().slice(0,10));
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(row.name+' · '+w.comparison)}"><defs><clipPath id="daily-clip"><rect x="${L}" y="${T}" width="${W-L-R}" height="${H-T-B}"/></clipPath></defs>${grid}<line x1="${x(data.date)}" x2="${x(data.date)}" y1="${T}" y2="${H-B}" stroke="#8091ab" stroke-dasharray="3 5"/><g clip-path="url(#daily-clip)">${marks}<path d="${path(actuals)}" fill="none" stroke="#edf4ff" stroke-width="2.5"/>${dots(actuals,'#edf4ff')}</g>${labels.map(d=>`<text x="${x(d)}" y="${H-22}" text-anchor="middle" fill="#9aaac0" font-size="12">${d.slice(5)}</text>`).join('')}</svg>`;
}

export function dailyMarkup(data,{locale='ko',selected=null,days=7,model='all',now=Date.now()}={}){
  const w=text[locale]||text.en;
  if(!validDaily(data))return `<h1>${w.title}</h1><p>${w.notReady}</p>`;
  const row=data.indicators.find(r=>r.id===selected)||data.indicators[0];
  if(!row)return `<h1>${w.title}</h1><p>${w.noData}</p>`;
  const stale=now-Date.parse(data.generated_ts_utc)>30*3600000;
  const actual=row.today_actual?`${fmt(row.today_actual.value,row.unit)} ${row.unit}`:row.actual_status==='market_closed'?w.closed:w.pending;
  const selectedForecasts=row.forecasts.filter(f=>model==='all'||model===f.model_id);
  const tomorrow=selectedForecasts.flatMap(f=>f.points).filter(p=>p.date>data.date).sort((a,b)=>a.date.localeCompare(b.date))[0];
  const allModels=[['chronos-2','Chronos-2'],['chronos-bolt-base','Chronos-Bolt']];
  const comparisons=allModels.filter(([id])=>model==='all'||model===id).map(([id,name])=>{
    const prev=row.previous_forecasts.find(f=>f.model_id===id)?.points.find(p=>p.date===data.date);
    const current=row.forecasts.find(f=>f.model_id===id);
    const future=current?.points.find(p=>p.date>data.date);
    return `<tr><th scope="row">${name}</th><td>${prev?fmt(prev.median,row.unit):'—'}</td><td>${row.today_actual?fmt(row.today_actual.value,row.unit):'—'}</td><td>${future?fmt(future.median,row.unit):'—'}<small>${future?esc(future.date):w.notReady}</small></td></tr>`;
  }).join('');
  return `<div class="daily-head"><span class="eyebrow">${w.kicker}</span><h1>${w.title}</h1><p>${w.note}</p><div class="daily-meta">${w.basis} ${esc(data.date)} · ${w.updated} ${esc(stamp(data.generated_ts_utc))} · ${esc(data.runtime?.device||'CUDA')}</div></div>${stale?`<p class="daily-warning" role="status">${w.stale}</p>`:''}
  <div class="daily-tabs" role="group" aria-label="Indicators">${data.indicators.map(r=>`<button data-daily-indicator="${esc(r.id)}" aria-pressed="${r.id===row.id}">${esc(r.id.toUpperCase().replace('ECB-',''))}</button>`).join('')}</div>
  <article class="daily-card"><div class="daily-card-top"><div><span class="eyebrow">${esc(row.group.toUpperCase())} · ${esc(row.unit)}</span><h2>${esc(row.name)}</h2></div><div class="daily-controls"><select data-daily-model aria-label="${w.model}"><option value="all" ${model==='all'?'selected':''}>${w.all}</option>${allModels.map(([id,name])=>`<option value="${id}" ${model===id?'selected':''}>${name}</option>`).join('')}</select><div role="group" aria-label="${w.history}">${[7,30].map(d=>`<button data-daily-days="${d}" aria-pressed="${days===d}">${d===7?w.seven:w.month}</button>`).join('')}</div></div></div>
  <div class="daily-summary"><div><span>${w.today} · ${esc(data.date)}</span><strong>${esc(actual)}</strong></div><div><span>${w.tomorrow}</span><strong>${tomorrow?esc(tomorrow.date):w.notReady}</strong></div><div><span>${w.one}</span><strong>ZERO-SHOT <small>· CUDA</small></strong></div></div>
  <div class="daily-legend"><span style="--swatch:#edf4ff">${w.actual}</span><span style="--swatch:#f7b955">${w.previous}</span><span style="--swatch:#53a6ff">Chronos-2 · ${w.next}</span><span style="--swatch:#5ce0cc">Chronos-Bolt · ${w.next}</span></div>
  <div class="daily-plot">${dailyChart(row,data,{days,model,locale})}</div><p class="daily-hint">${w.interval}</p>${!row.previous_forecasts.length?`<p class="daily-hint">${w.noPrior}</p>`:''}${row.source_error?`<p class="daily-warning">${w.pending} · ${esc(row.source_error)}</p>`:''}
  <div class="table-scroll"><table class="data-table"><thead><tr><th>${w.model}</th><th>${w.previous}</th><th>${w.today}</th><th>${w.tomorrow}</th></tr></thead><tbody>${comparisons}</tbody></table></div>
  <p class="daily-hint">${w.dates}</p><details class="daily-source"><summary>${w.licence}</summary><p>${esc(row.attribution)}</p><a href="${esc(row.license_url)}" target="_blank" rel="noreferrer">${esc(row.license_id)} ↗</a><p>Chronos-2 · Chronos-Bolt: Apache-2.0. Model forecasts are not source-provider forecasts.</p></details></article>
  <div class="daily-pending"><span class="eyebrow">${w.pendingIndex}</span><p>${w.indexNote}</p></div>`;
}
