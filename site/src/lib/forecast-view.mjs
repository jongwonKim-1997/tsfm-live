/** Shared static/browser rendering. All data text is escaped before HTML output. */
export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const numeric = value => typeof value === 'number' && Number.isFinite(value);
export function sourceAttributionMarkup(indicator,words) {
  const e=escapeHTML,t=key=>e(words[key]||key);
  const safeURL=value=>{try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password?url.href:null;}catch{return null;}};
  const sourceURL=safeURL(indicator.source_url),licenceURL=safeURL(indicator.license_url);
  const source=indicator.source_name||indicator.attribution;
  if(!source&&!indicator.license_id)return '';
  const sourceLabel=sourceURL?`<a href="${e(sourceURL)}" target="_blank" rel="noopener noreferrer">${e(source)}</a>`:e(source);
  const licence=indicator.license_id==='CC-BY-NC-4.0'?'CC BY-NC 4.0':indicator.license_id;
  const licenceLabel=licenceURL?`<a href="${e(licenceURL)}" target="_blank" rel="noopener noreferrer">${e(licence)}</a>`:e(licence);
  return `<div class="forecast-source-attribution"><p>${t('source')}: ${sourceLabel}${licence?` · ${licenceLabel}`:''}${indicator.license_id==='CC-BY-NC-4.0'?` · ${t('forecastNoncommercial')}`:''}</p>${indicator.observation_kind==='reference_rate'?`<p>${t('forecastReferenceNote')} ${t('forecastSourceFormatting')} ${t('forecastModelOrigin')}</p>`:''}</div>`;
}

export function observationWords(indicator,words) {
  return indicator.observation_kind==='reference_rate'?{...words,forecastLatestActual:words.forecastReferenceLatest,
    forecastActualZone:words.forecastReferenceZone,forecastObserved:words.forecastReferenceObserved}:words;
}
export const formatValue = (value, locale, decimals = 3) => numeric(value)
  ? new Intl.NumberFormat(locale === 'ko' ? 'ko-KR' : 'en-US', {minimumFractionDigits: Math.min(decimals, 2), maximumFractionDigits: decimals}).format(value) : '—';
const validBand = row => [row.lower,row.median,row.upper].every(numeric)&&row.lower<=row.median&&row.median<=row.upper;
export const usableForecast = row => row.status === 'ok' && ['available','expired'].includes(row.availability)
  && (Array.isArray(row.path)?row.path.length>0&&row.path.every((point,index)=>validBand(point)&&Number.isFinite(Date.parse(point.close_ts))
    && (index===0||Date.parse(point.close_ts)>Date.parse(row.path[index-1].close_ts))):validBand(row));
export const forecastPath = row => Array.isArray(row.path)?row.path:[{close_ts:row.next_close_ts||`${row.next_session_date}T00:00:00Z`,median:row.median,lower:row.lower,upper:row.upper}];
export function hourLabel(value,full=false) {
  if(!Number.isFinite(Date.parse(value)))return '—';
  const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value));
  const part=type=>parts.find(item=>item.type===type)?.value;
  return `${full?part('year')+'-':''}${part('month')}${full?'-':'/'}${part('day')} ${part('hour')}:${part('minute')}${full?' KST':''}`;
}
export const palette = ['#74aaff','#59d3ed','#a4a4ff','#e3ba79','#74d5be','#d79df4','#ec9dbc','#b6c9ed','#94a5bd','#eef4ff','#bba8ea'];
export function asViewed(indicator, now=Date.now()) {
  const entrants=(indicator.entrants||[]).map(row=>{
    if(indicator.frequency==='1h'&&Array.isArray(row.path)){
      const path=row.path.filter(point=>Date.parse(point.close_ts)>now);
      return {...row,path,next_close_ts:path[0]?.close_ts??null,availability:path.length?row.availability:'unavailable'};
    }
    return row.availability==='available'&&row.next_close_ts&&Date.parse(row.next_close_ts)<=now?{...row,availability:'expired'}:row;
  });
  const valid=entrants.filter(usableForecast);
  const expired=indicator.status==='available' && valid.length>0 && valid.every(row=>row.availability==='expired');
  return {...indicator,entrants,status:expired?'expired':indicator.frequency==='1h'&&indicator.status==='available'&&!valid.length?'unavailable':indicator.status};
}
export function chooseIndicator(indicators) {
  return indicators.find(row => row.status === 'available' && row.entrants.some(usableForecast))
    || indicators.find(row => row.enabled && row.last_observation)
    || indicators.find(row => row.enabled) || indicators[0];
}
export function historyFor(indicator, period) {
  const hourly=indicator.frequency==='1h';
  const points=(indicator.history?.[period === 'last7days' ? 'last7days' : 'today'] || [])
    .filter(point => numeric(point.value) && (hourly?Number.isFinite(Date.parse(point.close_ts)):/^\d{4}-\d{2}-\d{2}$/.test(point.session_date) && Number.isFinite(Date.parse(point.session_date))));
  return [...new Map(points.map(point=>[hourly?Date.parse(point.close_ts):point.session_date,point])).values()]
    .sort((a,b) => hourly?Date.parse(a.close_ts)-Date.parse(b.close_ts):a.session_date.localeCompare(b.session_date));
}
const dateLabel = value => value ? String(value).slice(5).replace('-', '/') : '—';
const dot = (x,y,r,attrs='') => `<circle cx="${x}" cy="${y}" r="${r}" ${attrs}/>`;

export function chartMarkup(indicator, period, locale, words, width = 1040) {
  words=observationWords(indicator,words);
  const t=key=>escapeHTML(words[key]||key), e=escapeHTML;
  const hourly=indicator.frequency==='1h';
  const rows=indicator.entrants||[], history=historyFor(indicator,period);
  const timeOf=point=>Date.parse(point.close_ts||`${point.session_date}T00:00:00Z`);
  const targetTime=row=>Date.parse(row.next_close_ts||`${row.next_session_date}T00:00:00Z`);
  const forecasts=rows.filter(row=>usableForecast(row)&&forecastPath(row).every(point=>Number.isFinite(Date.parse(point.close_ts))));
  const compact=width<600, w=Math.max(310,Math.round(width)), h=compact?300:340;
  const left=compact?53:75, right=w-24, top=39, bottom=h-38;
  const anchor=history.at(-1)||(hourly?indicator.last_observation:null), anchorTime=anchor?timeOf(anchor):null;
  const stamps=history.map(timeOf), targets=forecasts.flatMap(row=>forecastPath(row).map(point=>Date.parse(point.close_ts)));
  const times=[...stamps,...targets,...(anchor?[anchorTime]:[])].filter(Number.isFinite);
  const day=86400000;
  const minimum=times.length?Math.min(...times):0, maximum=times.length?Math.max(...times):day;
  const span=Math.max(maximum-minimum,day/4);
  // With one actual point, include time before it for a readable forward segment.
  // Every x coordinate still uses the same linear UTC-time scale, never model slots.
  const from=minimum-(history.length===1?span*.45:span*.035), until=maximum+span*.055;
  const x=time=>left+(time-from)/(until-from)*(right-left);
  const boundary=anchor?x(anchorTime):(left+right)/2;
  const values=[...history.map(row=>row.value),...forecasts.flatMap(row=>forecastPath(row).map(point=>point.median)),...(anchor?[anchor.value]:[])];
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
      const line=history.map((row,index)=>`${index&&(!hourly||stamps[index]-stamps[index-1]===3600000)?'L':'M'}${x(stamps[index])},${y(row.value)}`).join(' ');
      body.push(`${hourly?'':`<path d="${line} L${x(stamps.at(-1))},${bottom} L${x(stamps[0])},${bottom} Z" fill="var(--blue)" opacity=".06"/>`}<path class="forecast-actual-line" d="${line}" stroke="var(--blue)" stroke-width="2.8" fill="none" stroke-linejoin="round"/>`);
    }
  }
  // Model paths join forecast timestamps; no intermediate actuals are implied.
  rows.forEach((row,index)=>{
    if(!forecasts.includes(row))return;
    const path=forecastPath(row), color=palette[index%palette.length], final=path.at(-1);
    const label=`${row.name}: ${formatValue(final.median,locale,decimals)} [${formatValue(final.lower,locale,decimals)}, ${formatValue(final.upper,locale,decimals)}] ${unit}`;
    const start=anchor&&Date.parse(path[0].close_ts)>anchorTime?`M${boundary},${y(anchor.value)} `:'';
    const segments=path.map((point,index)=>`${start||index?'L':'M'}${x(Date.parse(point.close_ts))},${y(point.median)}`).join(' ');
    const segment=`<path class="forecast-model-line" d="${start+segments}" fill="none" stroke="${color}" stroke-width="${row.kind==='ensemble'?2.7:1.7}" stroke-dasharray="${row.kind==='baseline'?'2 6':'6 4'}" stroke-linecap="round"/>`;
    const markers=path.map((point,index)=>`<g><title>${e(hourly?hourLabel(point.close_ts,true):row.next_session_date)} · ${e(row.name)} · ${e(formatValue(point.median,locale,decimals))} [${e(formatValue(point.lower,locale,decimals))}, ${e(formatValue(point.upper,locale,decimals))}] ${e(unit)}</title>${dot(x(Date.parse(point.close_ts)),y(point.median),index===path.length-1?(compact?3:4):1.8,`class="forecast-endpoint" data-target-ts="${e(point.close_ts)}" fill="${color}" stroke="var(--panel)" stroke-width="${index===path.length-1?1.5:.6}"`)}</g>`).join('');
    body.push(`<g class="forecast-mark${row.availability==='expired'?' forecast-expired':''}" data-forecast-mark="${e(row.id)}"><title>${e(label)} · ${e(hourly?hourLabel(final.close_ts,true):row.next_session_date||indicator.next_session_date||'')}</title>${segment}${markers}</g>`);
  });
  history.forEach((row,index)=>{
    const last=index===history.length-1, xx=x(stamps[index]);
    body.push(`<g class="forecast-observation" data-observed-ts="${e(row.close_ts||row.session_date)}"><title>${e(hourly?hourLabel(row.close_ts,true):row.session_date)} · ${e(formatValue(row.value,locale,decimals))} ${e(unit)}${row.origin==='issued_context_anchor'?' · '+t('forecastAnchor'):''}</title>${last?dot(xx,y(row.value),8,'fill="var(--blue)" opacity=".15"'):''}${dot(xx,y(row.value),last?4:hourly?1.8:2.7,'fill="var(--blue)" stroke="var(--panel)" stroke-width="1.5"')}</g>`);
  });
  // Axis ticks are observed/target calendar dates; there is no categorical model axis.
  const ticks=new Map();
  history.forEach((row,index)=>ticks.set(stamps[index],{time:stamps[index],date:hourly?row.close_ts:row.session_date,priority:index===history.length-1?2:1}));
  forecasts.forEach(row=>forecastPath(row).forEach((point,index,path)=>ticks.set(Date.parse(point.close_ts),{time:Date.parse(point.close_ts),date:hourly?point.close_ts:row.next_session_date,priority:index===path.length-1?3:1})));
  const chosen=[];
  [...ticks.values()].sort((a,b)=>b.priority-a.priority||a.time-b.time).forEach(tick=>{
    if(chosen.every(other=>Math.abs(x(other.time)-x(tick.time))>(hourly?(compact?60:85):(compact?40:64))))chosen.push(tick);
  });
  chosen.sort((a,b)=>a.time-b.time).forEach(tick=>body.push(`<text x="${x(tick.time)}" y="${bottom+25}" text-anchor="middle" class="forecast-axis forecast-date-tick" data-date="${e(tick.date)}">${e(hourly?hourLabel(tick.date):dateLabel(tick.date))}</text>`));
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
  words=observationWords(indicator,words);
  const t=key=>escapeHTML(words[key]||key), e=escapeHTML;
  const hourly=indicator.frequency==='1h';
  const latest=indicator.last_observation;
  const unit=indicator.unit_label||indicator.unit;
  const valid=(indicator.entrants||[]).filter(usableForecast);
  const status=indicator.status==='available'?'forecastPublished':indicator.status==='expired'?'forecastExpired':indicator.status==='disabled'?'disabled':'forecastAwaiting';
  const rows=(indicator.entrants||[]).map((row,index)=>{
    const good=usableForecast(row), color=palette[index%palette.length];
    const lastPoint=hourly?row.path?.at(-1):row;
    const value=formatValue(lastPoint?.median,locale,indicator.decimals??3);
    const interval=good?`${formatValue(lastPoint.lower,locale,indicator.decimals??3)} – ${formatValue(lastPoint.upper,locale,indicator.decimals??3)}`:t(row.availability==='disabled'?'disabled':row.status==='failed'?'failed':row.status==='void'?'void':row.status==='skipped'?'skipped':'pending');
    const inner=`<span class="forecast-model-name"><span class="forecast-model-key" style="--model-color:${color}" aria-hidden="true"></span><span>${e(row.name)}<small>${t(row.kind)}</small></span></span><span class="forecast-model-value">${good?e(value):'—'}<small>${e(interval)}</small></span>`;
    return good?`<button type="button" class="forecast-model" data-highlight-model="${e(row.id)}" aria-pressed="false" aria-describedby="forecast-legend-note">${inner}</button>`:`<div class="forecast-model forecast-model-unavailable">${inner}</div>`;
  }).join('');
  const observations=historyFor(indicator,period);
  const finalForecast=valid.flatMap(forecastPath).sort((a,b)=>Date.parse(a.close_ts)-Date.parse(b.close_ts)).at(-1);
  const nextForecast=valid.flatMap(forecastPath).sort((a,b)=>Date.parse(a.close_ts)-Date.parse(b.close_ts))[0];
  const computed=indicator.mode==='local_zero_shot'&&valid.length>0&&indicator.forecast_generated_ts_utc
    ? `<p class="forecast-computation-note">${t('forecastInputDate')} <time>${e(hourly?hourLabel(indicator.forecast_anchor?.close_ts||latest?.close_ts,true):indicator.forecast_anchor?.session_date||latest?.session_date||'—')}</time> · ${t('forecastComputedAt')} <time>${e(indicator.forecast_generated_ts_utc)}</time></p>`:'';
  const context=Number.isInteger(indicator.context_length)&&indicator.context_length>0?`<p class="forecast-context-note">${t('forecastContextLength')}: ${e(indicator.context_length)} ${t(hourly?'forecastContextHours':'forecastContextObservations')}</p>`:'';
  const actualTable=observations.length?`<details class="forecast-actual-table"><summary>${t('forecastActualTable')} · ${observations.length}</summary><table><caption class="sr-only">${e(indicator.name)} · ${t('forecastObserved')}</caption><thead><tr><th scope="col">${t('date')}</th><th scope="col">${e(unit)}</th><th scope="col">${t('source')}</th></tr></thead><tbody>${observations.map(row=>`<tr><th scope="row">${e(hourly?hourLabel(row.close_ts,true):row.session_date)}</th><td>${e(formatValue(row.value,locale,indicator.decimals??3))}</td><td>${t(row.origin==='issued_context_anchor'?'forecastAnchor':'forecastObserved')}${row.corrected?' · '+t('corrected'):''}</td></tr>`).join('')}</tbody></table></details>`:'';
  return `<div class="forecast-panel-heading"><div><div class="forecast-instrument-title"><h2>${e(indicator.name)}</h2><span class="forecast-state ${indicator.status==='expired'?'is-expired':''}">${t(status)}</span></div><div class="forecast-last-value">${e(formatValue(latest?.value,locale,indicator.decimals??3))}<span>${e(unit)}</span></div><p>${t('forecastLatestActual')} <time>${e(hourly?hourLabel(latest?.close_ts,true):latest?.session_date||'—')}</time>${latest?.origin==='issued_context_anchor'?` · ${t('forecastAnchor')}`:''}</p></div><div class="forecast-target"><span>${t('forecastNextSession')}</span><strong>${e(hourly?hourLabel(finalForecast?.close_ts):indicator.next_session_date||'—')}</strong><small>${hourly?`${e(hourLabel(nextForecast?.close_ts))} → ${e(hourLabel(finalForecast?.close_ts))} KST`:e(indicator.next_session_timezone||'')} · ${valid.length} ${t('forecastAvailableModels')}</small></div></div>
    <div class="forecast-plot">${chartMarkup(indicator,period,locale,words,width)}</div>
    <div class="forecast-chart-key" id="forecast-legend-note"><span><i class="forecast-actual-key"></i>${t('forecastObserved')}</span><span><i class="forecast-prediction-key"></i>${t('forecastMedianLine')}<span class="forecast-interval-note">${t('forecastIntervalsBelow')}</span></span><span class="forecast-chart-unit">${e(unit)}</span></div>
    <div class="forecast-model-grid" aria-label="${t('forecastModelLegend')}">${rows}</div>
    <div class="forecast-footnote"><p>${t(period==='last7days'?'forecastSevenNote':'forecastTodayNote')} ${t('forecastSameSession')}</p>${observations.length===1?`<p>${t('forecastSingleObservation')}</p>`:''}${computed}${context}${sourceAttributionMarkup(indicator,words)}${indicator.status==='expired'?`<p class="forecast-expiry-note">${t('forecastExpiredNote')}</p>`:''}${indicator.status==='disabled'?`<p>${t('forecastDisabledNote')}</p>`:''}${actualTable}</div>`;
}
