/** Shared static/browser rendering. All data text is escaped before HTML output. */
export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const numeric = value => typeof value === 'number' && Number.isFinite(value);
export const formatValue = (value, locale, decimals = 3) => numeric(value)
  ? new Intl.NumberFormat(locale === 'ko' ? 'ko-KR' : 'en-US', {minimumFractionDigits: Math.min(decimals, 2), maximumFractionDigits: decimals}).format(value) : '—';
export const usableForecast = row => row.status === 'ok' && ['available','expired'].includes(row.availability) && [row.lower, row.median, row.upper].every(numeric)
  && row.lower <= row.median && row.median <= row.upper;
export const palette = ['#74aaff','#59d3ed','#a4a4ff','#e3ba79','#74d5be','#d79df4','#ec9dbc','#b6c9ed','#94a5bd','#eef4ff','#bba8ea'];
export function asViewed(indicator, now=Date.now()) {
  const entrants=(indicator.entrants||[]).map(row=>row.availability==='available' && row.next_close_ts && Date.parse(row.next_close_ts)<=now
    ? {...row,availability:'expired'} : row);
  const valid=entrants.filter(usableForecast);
  const expired=indicator.status==='available' && valid.length>0 && valid.every(row=>row.availability==='expired');
  return {...indicator,entrants,status:expired?'expired':indicator.status};
}
export function chooseIndicator(indicators) {
  return indicators.find(row => row.status === 'available' && row.entrants.some(usableForecast))
    || indicators.find(row => row.enabled && row.last_observation)
    || indicators.find(row => row.enabled) || indicators[0];
}
export function historyFor(indicator, period) {
  const points=(indicator.history?.[period === 'last7days' ? 'last7days' : 'today'] || [])
    .filter(point => numeric(point.value) && /^\d{4}-\d{2}-\d{2}$/.test(point.session_date) && Number.isFinite(Date.parse(point.session_date)));
  return [...new Map(points.map(point=>[point.session_date,point])).values()]
    .sort((a,b) => a.session_date.localeCompare(b.session_date));
}
const dateLabel = value => value ? String(value).slice(5).replace('-', '/') : '—';
const dot = (x,y,r,attrs='') => `<circle cx="${x}" cy="${y}" r="${r}" ${attrs}/>`;

export function chartMarkup(indicator, period, locale, words, width = 1040) {
  const t=key=>escapeHTML(words[key]||key), e=escapeHTML;
  const rows=indicator.entrants||[], history=historyFor(indicator,period);
  const timeOf=point=>Date.parse(point.close_ts||`${point.session_date}T00:00:00Z`);
  const targetTime=row=>Date.parse(row.next_close_ts||`${row.next_session_date}T00:00:00Z`);
  const forecasts=rows.filter(row=>usableForecast(row)&&Number.isFinite(targetTime(row)));
  const compact=width<600, w=Math.max(310,Math.round(width)), h=compact?300:340;
  const left=compact?53:75, right=w-24, top=39, bottom=h-38;
  const stamps=history.map(timeOf), targets=forecasts.map(targetTime);
  const times=[...stamps,...targets].filter(Number.isFinite);
  const day=86400000;
  const minimum=times.length?Math.min(...times):0, maximum=times.length?Math.max(...times):day;
  const span=Math.max(maximum-minimum,day/4);
  // With one actual point, include time before it for a readable forward segment.
  // Every x coordinate still uses the same linear UTC-time scale, never model slots.
  const from=minimum-(history.length===1?span*.45:span*.035), until=maximum+span*.055;
  const x=time=>left+(time-from)/(until-from)*(right-left);
  const anchor=history.at(-1), anchorTime=anchor?timeOf(anchor):null;
  const boundary=anchor?x(anchorTime):(left+right)/2;
  const values=[...history.map(row=>row.value),...forecasts.map(row=>row.median)];
  const decimals=indicator.decimals??3, unit=indicator.unit_label||indicator.unit;
  const range=values.length?Math.max(...values)-Math.min(...values):0;
  const pad=range>0?range*.2:Math.max(Math.abs(values[0]||0)*.005,.01);
  const low=values.length?Math.min(...values)-pad:0, high=values.length?Math.max(...values)+pad:1;
  const y=value=>bottom-(value-low)/(high-low)*(bottom-top);
  const body=[];
  body.push(`<rect x="${boundary}" y="${top-18}" width="${Math.max(0,right-boundary+10)}" height="${bottom-top+22}" rx="8" fill="var(--blue-soft)" opacity=".22"/>`);
  for(let n=0;n<5;n++){
    const value=low+(high-low)*n/4, yy=y(value);
    body.push(`<line x1="${left}" x2="${right}" y1="${yy}" y2="${yy}" stroke="var(--line)" stroke-dasharray="2 5"/><text x="${left-10}" y="${yy+4}" text-anchor="end" class="forecast-axis">${values.length?e(formatValue(value,locale,decimals)):'—'}</text>`);
  }
  body.push(`<text x="${left}" y="17" class="forecast-zone">${t('forecastActualZone')}</text><text x="${right}" y="17" text-anchor="end" class="forecast-zone">${t('forecastModelZone')}</text>`);
  if(anchor){
    body.push(`<line x1="${boundary}" x2="${boundary}" y1="${top-12}" y2="${bottom+8}" stroke="var(--blue)" stroke-opacity=".45" stroke-dasharray="3 5"/>`);
    if(history.length>1){
      const line=history.map((row,index)=>`${index?'L':'M'}${x(stamps[index])},${y(row.value)}`).join(' ');
      body.push(`<path d="${line} L${x(stamps.at(-1))},${bottom} L${x(stamps[0])},${bottom} Z" fill="var(--blue)" opacity=".06"/><path class="forecast-actual-line" d="${line}" stroke="var(--blue)" stroke-width="2.8" fill="none" stroke-linejoin="round"/>`);
    }
  }
  // Dashed segments denote one-session model outputs, not intermediate actuals.
  rows.forEach((row,index)=>{
    if(!forecasts.includes(row))return;
    const xx=x(targetTime(row)), yy=y(row.median), color=palette[index%palette.length];
    const label=`${row.name}: ${formatValue(row.median,locale,decimals)} [${formatValue(row.lower,locale,decimals)}, ${formatValue(row.upper,locale,decimals)}] ${unit}`;
    const segment=anchor&&targetTime(row)>anchorTime?`<path class="forecast-model-line" d="M${boundary},${y(anchor.value)} L${xx},${yy}" fill="none" stroke="${color}" stroke-width="${row.kind==='ensemble'?2.7:1.7}" stroke-dasharray="${row.kind==='baseline'?'2 6':'6 4'}" stroke-linecap="round"/>`:'';
    body.push(`<g class="forecast-mark${row.availability==='expired'?' forecast-expired':''}" data-forecast-mark="${e(row.id)}"><title>${e(label)} · ${e(row.next_session_date||indicator.next_session_date||'')}</title>${segment}${dot(xx,yy,compact?3:4,`class="forecast-endpoint" data-target-ts="${e(row.next_close_ts||row.next_session_date)}" fill="${color}" stroke="var(--panel)" stroke-width="1.5"`)}</g>`);
  });
  history.forEach((row,index)=>{
    const last=index===history.length-1, xx=x(stamps[index]);
    body.push(`<g class="forecast-observation"><title>${e(row.session_date)} · ${e(formatValue(row.value,locale,decimals))} ${e(unit)}${row.origin==='issued_context_anchor'?' · '+t('forecastAnchor'):''}</title>${last?dot(xx,y(row.value),8,'fill="var(--blue)" opacity=".15"'):''}${dot(xx,y(row.value),last?4:2.7,'fill="var(--blue)" stroke="var(--panel)" stroke-width="1.5"')}</g>`);
  });
  // Axis ticks are observed/target calendar dates; there is no categorical model axis.
  const ticks=new Map();
  history.forEach((row,index)=>ticks.set(stamps[index],{time:stamps[index],date:row.session_date,priority:index===history.length-1?2:1}));
  forecasts.forEach(row=>ticks.set(targetTime(row),{time:targetTime(row),date:row.next_session_date,priority:3}));
  const chosen=[];
  [...ticks.values()].sort((a,b)=>b.priority-a.priority||a.time-b.time).forEach(tick=>{
    if(chosen.every(other=>Math.abs(x(other.time)-x(tick.time))>(compact?40:64)))chosen.push(tick);
  });
  chosen.sort((a,b)=>a.time-b.time).forEach(tick=>body.push(`<text x="${x(tick.time)}" y="${bottom+25}" text-anchor="middle" class="forecast-axis forecast-date-tick" data-date="${e(tick.date)}">${e(dateLabel(tick.date))}</text>`));
  if(!history.length)body.push(`<text x="${(left+boundary)/2}" y="${(top+bottom)/2}" text-anchor="middle" class="forecast-axis">${t('forecastNoActual')}</text>`);
  if(!forecasts.length)body.push(`<text x="${(boundary+right)/2}" y="${(top+bottom)/2}" text-anchor="middle" class="forecast-axis">${t('forecastNoOutput')}</text>`);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${e(indicator.name)} · ${t('forecastChartLabel')} · ${e(unit)}"><title>${e(indicator.name)} · ${t('forecastChartLabel')}</title>${body.join('')}</svg>`;
}

export function highlightForecast(panel, id) {
  panel.querySelectorAll('[data-forecast-mark]').forEach(mark=>{
    mark.classList.toggle('is-dim',Boolean(id)&&mark.dataset.forecastMark!==id);
    mark.classList.toggle('is-focused',Boolean(id)&&mark.dataset.forecastMark===id);
  });
}
export function panelMarkup(indicator, period, locale, words, width=1040) {
  const t=key=>escapeHTML(words[key]||key), e=escapeHTML;
  const latest=indicator.last_observation;
  const unit=indicator.unit_label||indicator.unit;
  const valid=(indicator.entrants||[]).filter(usableForecast);
  const status=indicator.status==='available'?'forecastPublished':indicator.status==='expired'?'forecastExpired':indicator.status==='disabled'?'disabled':'forecastAwaiting';
  const rows=(indicator.entrants||[]).map((row,index)=>{
    const good=usableForecast(row), color=palette[index%palette.length];
    const value=formatValue(row.median,locale,indicator.decimals??3);
    const interval=good?`${formatValue(row.lower,locale,indicator.decimals??3)} – ${formatValue(row.upper,locale,indicator.decimals??3)}`:t(row.availability==='disabled'?'disabled':row.status==='failed'?'failed':row.status==='void'?'void':row.status==='skipped'?'skipped':'pending');
    const inner=`<span class="forecast-model-name"><span class="forecast-model-key" style="--model-color:${color}" aria-hidden="true"></span><span>${e(row.name)}<small>${t(row.kind)}</small></span></span><span class="forecast-model-value">${good?e(value):'—'}<small>${e(interval)}</small></span>`;
    return good?`<button type="button" class="forecast-model" data-highlight-model="${e(row.id)}" aria-pressed="false" aria-describedby="forecast-legend-note">${inner}</button>`:`<div class="forecast-model forecast-model-unavailable">${inner}</div>`;
  }).join('');
  const observations=historyFor(indicator,period);
  const actualTable=observations.length?`<details class="forecast-actual-table"><summary>${t('forecastActualTable')} · ${observations.length}</summary><table><caption class="sr-only">${e(indicator.name)} · ${t('forecastObserved')}</caption><thead><tr><th scope="col">${t('date')}</th><th scope="col">${e(unit)}</th><th scope="col">${t('source')}</th></tr></thead><tbody>${observations.map(row=>`<tr><th scope="row">${e(row.session_date)}</th><td>${e(formatValue(row.value,locale,indicator.decimals??3))}</td><td>${t(row.origin==='issued_context_anchor'?'forecastAnchor':'forecastObserved')}${row.corrected?' · '+t('corrected'):''}</td></tr>`).join('')}</tbody></table></details>`:'';
  return `<div class="forecast-panel-heading"><div><div class="forecast-instrument-title"><h2>${e(indicator.name)}</h2><span class="forecast-state ${indicator.status==='expired'?'is-expired':''}">${t(status)}</span></div><div class="forecast-last-value">${e(formatValue(latest?.value,locale,indicator.decimals??3))}<span>${e(unit)}</span></div><p>${t('forecastLatestActual')} <time>${e(latest?.session_date||'—')}</time>${latest?.origin==='issued_context_anchor'?` · ${t('forecastAnchor')}`:''}</p></div><div class="forecast-target"><span>${t('forecastNextSession')}</span><strong>${e(indicator.next_session_date||'—')}</strong><small>${e(indicator.next_session_timezone||'')} · ${valid.length} ${t('forecastAvailableModels')}</small></div></div>
    <div class="forecast-plot">${chartMarkup(indicator,period,locale,words,width)}</div>
    <div class="forecast-chart-key" id="forecast-legend-note"><span><i class="forecast-actual-key"></i>${t('forecastObserved')}</span><span><i class="forecast-prediction-key"></i>${t('forecastMedianLine')}<span class="forecast-interval-note">${t('forecastIntervalsBelow')}</span></span><span class="forecast-chart-unit">${e(unit)}</span></div>
    <div class="forecast-model-grid" aria-label="${t('forecastModelLegend')}">${rows}</div>
    <div class="forecast-footnote"><p>${t(period==='last7days'?'forecastSevenNote':'forecastTodayNote')} ${t('forecastSameSession')}</p>${indicator.status==='expired'?`<p class="forecast-expiry-note">${t('forecastExpiredNote')}</p>`:''}${indicator.status==='disabled'?`<p>${t('forecastDisabledNote')}</p>`:''}${actualTable}</div>`;
}
