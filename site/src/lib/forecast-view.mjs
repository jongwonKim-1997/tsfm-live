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
  const t = key => escapeHTML(words[key] || key);
  const rows = indicator.entrants || [];
  const forecasts = rows.filter(usableForecast);
  const history = historyFor(indicator, period);
  const compact = width < 600;
  const w = Math.max(310, Math.round(width)), h = compact ? 300 : 308;
  const left = compact ? 53 : 75, right = w - 18, top = 39, bottom = h - 38;
  const boundary = left + (right - left) * (compact ? .29 : .43);
  const values = [...history.map(row => row.value), ...forecasts.flatMap(row => [row.lower,row.upper])];
  const decimals = indicator.decimals ?? 3;
  const unit = indicator.unit_label || indicator.unit;
  const range = values.length ? Math.max(...values) - Math.min(...values) : 0;
  const pad = range > 0 ? range * .19 : Math.max(Math.abs(values[0] || 0) * .005, .01);
  const low = values.length ? Math.min(...values) - pad : 0;
  const high = values.length ? Math.max(...values) + pad : 1;
  const y = value => bottom - (value - low) / (high - low) * (bottom-top);
  const body = [];
  body.push(`<rect x="${boundary}" y="${top-18}" width="${right-boundary+10}" height="${bottom-top+22}" rx="8" fill="var(--blue-soft)" opacity=".24"/>`);
  for(let n=0;n<5;n++) {
    const value=low+(high-low)*n/4, yy=y(value);
    body.push(`<line x1="${left}" x2="${right}" y1="${yy}" y2="${yy}" stroke="var(--line)" stroke-dasharray="2 5"/>`);
    body.push(`<text x="${left-10}" y="${yy+4}" text-anchor="end" class="forecast-axis">${values.length?escapeHTML(formatValue(value,locale,decimals)):'—'}</text>`);
  }
  body.push(`<text x="${left}" y="17" class="forecast-zone">${t('forecastActualZone')}</text><text x="${boundary+12}" y="17" class="forecast-zone">${t('forecastModelZone')}</text>`);
  body.push(`<line x1="${boundary}" x2="${boundary}" y1="${top-12}" y2="${bottom+8}" stroke="var(--blue)" stroke-opacity=".5" stroke-dasharray="3 5"/>`);
  if(history.length) {
    const x0=left+8, x1=boundary-18;
    const stamps=history.map(row=>Date.parse(`${row.session_date}T00:00:00Z`));
    const span=stamps.at(-1)-stamps[0];
    const xx=index=>history.length===1?(x0+x1)/2:x0+(stamps[index]-stamps[0])/span*(x1-x0);
    if(history.length>1) {
      const line=history.map((row,index)=>`${index?'L':'M'}${xx(index)},${y(row.value)}`).join(' ');
      body.push(`<path d="${line} L${xx(history.length-1)},${bottom} L${xx(0)},${bottom} Z" fill="var(--blue)" opacity=".055"/><path d="${line}" stroke="var(--blue)" stroke-width="2.5" fill="none" stroke-linejoin="round"/>`);
    }
    history.forEach((row,index)=>{
      const last=index===history.length-1;
      body.push(`<g class="forecast-observation"><title>${escapeHTML(row.session_date)} · ${escapeHTML(formatValue(row.value,locale,decimals))} ${escapeHTML(unit)}${row.origin==='issued_context_anchor'?' · '+t('forecastAnchor'):''}</title>${last?dot(xx(index),y(row.value),8,'fill="var(--blue)" opacity=".15"'):''}${dot(xx(index),y(row.value),last?4:2.7,'fill="var(--blue)" stroke="var(--panel)" stroke-width="1.5"')}</g>`);
      if(last || (!compact && (history.length<5 || index%2===0)) || index===0) {
        body.push(`<text x="${xx(index)}" y="${bottom+25}" text-anchor="middle" class="forecast-axis">${escapeHTML(dateLabel(row.session_date))}</text>`);
      }
    });
    body.push(`<line x1="${boundary+4}" x2="${right}" y1="${y(history.at(-1).value)}" y2="${y(history.at(-1).value)}" stroke="var(--muted)" stroke-opacity=".45" stroke-dasharray="3 6"/>`);
  }
  const start=boundary+14, end=right-6, slot=(end-start)/Math.max(rows.length,1);
  rows.forEach((row,index)=>{
    const x=start+slot*(index+.5), color=palette[index%palette.length];
    body.push(`<text x="${x}" y="${bottom+25}" text-anchor="middle" class="forecast-axis">${index+1}</text>`);
    if(!usableForecast(row))return;
    const label=`${row.name}: ${formatValue(row.median,locale,decimals)} [${formatValue(row.lower,locale,decimals)}, ${formatValue(row.upper,locale,decimals)}] ${unit}`;
    const cap=Math.min(compact?4:7,slot*.3);
    body.push(`<g class="forecast-mark${row.availability==='expired'?' forecast-expired':''}" data-forecast-mark="${escapeHTML(row.id)}"><title>${escapeHTML(label)} · ${escapeHTML(row.next_session_date||indicator.next_session_date||'')}</title><rect x="${x-cap}" y="${y(row.upper)}" width="${cap*2}" height="${Math.max(1,y(row.lower)-y(row.upper))}" rx="${cap}" fill="${color}" opacity=".1"/><path d="M${x},${y(row.lower)} V${y(row.upper)} M${x-cap},${y(row.lower)} H${x+cap} M${x-cap},${y(row.upper)} H${x+cap}" stroke="${color}" stroke-width="1.6" fill="none"/>${dot(x,y(row.median),compact?3:4.5,`fill="${color}" stroke="var(--panel)" stroke-width="1.5"`)}</g>`);
  });
  if(!history.length) body.push(`<text x="${(left+boundary)/2}" y="${(top+bottom)/2}" text-anchor="middle" class="forecast-axis">${t('forecastNoActual')}</text>`);
  if(!forecasts.length) body.push(`<text x="${(boundary+right)/2}" y="${(top+bottom)/2}" text-anchor="middle" class="forecast-axis">${t('forecastNoOutput')}</text>`);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${escapeHTML(indicator.name)} · ${t('forecastChartLabel')} · ${escapeHTML(unit)}"><title>${escapeHTML(indicator.name)} · ${t('forecastChartLabel')}</title>${body.join('')}</svg>`;
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
    const inner=`<span class="forecast-model-name"><span class="forecast-model-key" style="--model-color:${color}">${index+1}</span><span>${e(row.name)}<small>${t(row.kind)}</small></span></span><span class="forecast-model-value">${good?e(value):'—'}<small>${e(interval)}</small></span>`;
    return good?`<button type="button" class="forecast-model" data-highlight-model="${e(row.id)}" aria-pressed="false" aria-describedby="forecast-legend-note">${inner}</button>`:`<div class="forecast-model forecast-model-unavailable">${inner}</div>`;
  }).join('');
  const observations=historyFor(indicator,period);
  const actualTable=observations.length?`<details class="forecast-actual-table"><summary>${t('forecastActualTable')} · ${observations.length}</summary><table><caption class="sr-only">${e(indicator.name)} · ${t('forecastObserved')}</caption><thead><tr><th scope="col">${t('date')}</th><th scope="col">${e(unit)}</th><th scope="col">${t('source')}</th></tr></thead><tbody>${observations.map(row=>`<tr><th scope="row">${e(row.session_date)}</th><td>${e(formatValue(row.value,locale,indicator.decimals??3))}</td><td>${t(row.origin==='issued_context_anchor'?'forecastAnchor':'forecastObserved')}${row.corrected?' · '+t('corrected'):''}</td></tr>`).join('')}</tbody></table></details>`:'';
  return `<div class="forecast-panel-heading"><div><div class="forecast-instrument-title"><h2>${e(indicator.name)}</h2><span class="forecast-state ${indicator.status==='expired'?'is-expired':''}">${t(status)}</span></div><div class="forecast-last-value">${e(formatValue(latest?.value,locale,indicator.decimals??3))}<span>${e(unit)}</span></div><p>${t('forecastLatestActual')} <time>${e(latest?.session_date||'—')}</time>${latest?.origin==='issued_context_anchor'?` · ${t('forecastAnchor')}`:''}</p></div><div class="forecast-target"><span>${t('forecastNextSession')}</span><strong>${e(indicator.next_session_date||'—')}</strong><small>${e(indicator.next_session_timezone||'')} · ${valid.length} ${t('forecastAvailableModels')}</small></div></div>
    <div class="forecast-plot">${chartMarkup(indicator,period,locale,words,width)}</div>
    <div class="forecast-chart-key" id="forecast-legend-note"><span><i class="forecast-actual-key"></i>${t('forecastObserved')}</span><span><i class="forecast-median-key"></i>${t('median')}<i class="forecast-interval-key"></i>${t('interval80')}</span><span class="forecast-chart-unit">${e(unit)}</span></div>
    <div class="forecast-model-grid" aria-label="${t('forecastModelLegend')}">${rows}</div>
    <div class="forecast-footnote"><p>${t(period==='last7days'?'forecastSevenNote':'forecastTodayNote')} ${t('forecastSameSession')}</p>${indicator.status==='expired'?`<p class="forecast-expiry-note">${t('forecastExpiredNote')}</p>`:''}${indicator.status==='disabled'?`<p>${t('forecastDisabledNote')}</p>`:''}${actualTable}</div>`;
}
