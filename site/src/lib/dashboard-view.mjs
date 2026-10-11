import {asViewed,chooseIndicator,escapeHTML,formatValue,panelMarkup,usableForecast} from './forecast-view.mjs';

const validDate=value=>typeof value==='string' && Number.isFinite(Date.parse(value));
const validPoint=point=>point && typeof point.value==='number' && Number.isFinite(point.value)
  && /^\d{4}-\d{2}-\d{2}$/.test(point.session_date) && validDate(point.close_ts);

export function validLocalDashboard(data,now=Date.now()) {
  return data?.mode==='local_zero_shot' && data.public_ledger_eligible===false
    && data.inference_mode==='zero_shot' && validDate(data.generated_ts_utc) && validDate(data.run_ts_utc)
    && Date.parse(data.generated_ts_utc)<=now+300000 && Date.parse(data.run_ts_utc)<=Date.parse(data.generated_ts_utc)
    && Array.isArray(data.indicators) && data.indicators.length>0
    && data.indicators.every(row=>row && typeof row.id==='string' && typeof row.name==='string'
      && Array.isArray(row.entrants) && row.history && Array.isArray(row.history.today) && Array.isArray(row.history.last7days)
      && (!row.last_observation||validPoint(row.last_observation))
      && [...row.history.today,...row.history.last7days].every(validPoint));
}

export function chooseDashboardData(local,ledger,now=Date.now()) {
  // A local dashboard never supersedes a newer, usable public record.
  const publicTime=Date.parse(ledger?.run_ts_utc||'');
  const localTime=Date.parse(local?.run_ts_utc||'');
  const newerPublic=Number.isFinite(publicTime)&&publicTime>localTime
    && ledger?.indicators?.some(row=>(row.entrants||[]).some(usableForecast));
  return validLocalDashboard(local,now)&&!newerPublic?local:ledger;
}

export function prepareDashboard(data,now=Date.now()) {
  const local=data.mode==='local_zero_shot';
  const indicators=(data.indicators||[]).map(indicator=>{
    if(!local)return asViewed(indicator,now);
    const anchorTime=Date.parse(indicator.last_observation?.close_ts||'');
    const computed=Object.hasOwn(indicator,'forecast_generated_ts_utc')?indicator.forecast_generated_ts_utc:data.forecast_generated_ts_utc;
    const generated=Date.parse(computed||'');
    const entrants=indicator.entrants.map(row=>{
      const target=Date.parse(row.next_close_ts||'');
      return usableForecast(row)&&(!Number.isFinite(anchorTime)||!Number.isFinite(target)||!Number.isFinite(generated)||target<=anchorTime||target<=generated)
        ? {...row,status:'failed',availability:'unavailable'}:row;
    });
    const ready=entrants.some(usableForecast);
    return asViewed({...indicator,mode:data.mode,collection_ts_utc:indicator.collection_ts_utc??null,
      forecast_generated_ts_utc:computed??null,entrants,
      status:!ready&&indicator.status==='available'?'unavailable':indicator.status},now);
  });
  return {...data,indicators};
}

export function dashboardWords(words,local) {
  return local?{...words,forecastPublished:words.forecastLocalReady,forecastAwaiting:words.forecastLocalAwaiting,
    forecastNoOutput:words.forecastLocalNoOutput,forecastEyebrow:words.forecastLocalMode,
    forecastTitle:words.forecastLocalTitle,forecastSessionNote:words.forecastLocalSessionNote}:words;
}

export function dashboardTimestamp(value,locale) {
  if(!validDate(value))return '—';
  return new Intl.DateTimeFormat(locale==='ko'?'ko-KR':'en-GB',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value))+' KST';
}

export function dashboardProvenance(data,locale,words,now=Date.now()) {
  if(data.mode!=='local_zero_shot')return '';
  const e=escapeHTML, t=key=>e(words[key]||key);
  const stale=now-Date.parse(data.generated_ts_utc)>36*3600000;
  return `<div class="forecast-provenance" data-dashboard-provenance><strong>${t('forecastLocalMode')}</strong><span>${t('forecastCollectedAt')} <time${data.collection_ts_utc?` datetime="${e(data.collection_ts_utc)}"`:''}>${e(dashboardTimestamp(data.collection_ts_utc,locale))}</time></span><span>${t('forecastGeneratedAt')} <time datetime="${e(data.generated_ts_utc)}">${e(dashboardTimestamp(data.generated_ts_utc,locale))}</time></span><p>${t('forecastLocalEvidence')}${stale?' <b class="forecast-expiry-note">'+t('forecastSnapshotStale')+'</b>':''}</p></div>`;
}

export function dashboardBoardMarkup(raw,locale,baseWords,{now=Date.now(),recordHref=null}={}) {
  const data=prepareDashboard(raw,now), local=data.mode==='local_zero_shot';
  const words=dashboardWords(baseWords,local), e=escapeHTML, t=key=>e(words[key]||key);
  const indicators=data.indicators, selected=chooseIndicator(indicators), featured=indicators.filter(row=>row.enabled).slice(0,3);
  const period='last7days';
  const json=JSON.stringify(data).replace(/</g,'\\u003c');
  return `<section class="forecast-board" data-forecast-board data-selected="${e(selected?.id)}" data-period="${period}" data-mode="${e(data.mode||'public_ledger')}" aria-labelledby="forecast-title">
    <div class="forecast-heading"><div><span class="eyebrow"><span class="status-dot"></span>${t('forecastEyebrow')}</span><h1 id="forecast-title">${t('forecastTitle')}</h1></div><div class="forecast-history-control"><span>${t('forecastHistoryRange')}</span><div class="window-tabs" role="group" aria-label="${t('forecastHistoryRange')}"><button type="button" data-history-period="today" aria-pressed="false">${t('forecastToday')}</button><button type="button" data-history-period="last7days" aria-pressed="true">${t('forecastSevenDays')}</button></div></div></div>
    ${dashboardProvenance(data,locale,words,now)}
    <div class="forecast-market-bar"><div class="forecast-featured" role="group" aria-label="${t('forecastChooseIndicator')}">${featured.map(row=>`<button type="button" class="forecast-market" data-indicator="${e(row.id)}" aria-pressed="${row.id===selected?.id}"><span>${e(row.name)}</span><strong>${e(formatValue(row.last_observation?.value,locale,row.decimals??3))}<small>${e(row.unit_label||row.unit)} · ${e(row.last_observation?.session_date||'—')}</small></strong></button>`).join('')}</div><label class="forecast-all-indicators"><span>${t('forecastAllIndicators')}</span><select data-indicator-select aria-label="${t('forecastChooseIndicator')}">${indicators.map(row=>`<option value="${e(row.id)}"${row.id===selected?.id?' selected':''}>${e(row.name)}${!row.enabled?' · '+t('disabled'):''}</option>`).join('')}</select></label></div>
    <div class="forecast-stage panel" data-forecast-panel>${selected?panelMarkup(selected,period,locale,words):''}</div>
    <div class="forecast-record-note"><span>${t('forecastSessionNote')}</span>${recordHref?`<a class="text-link" href="${e(recordHref)}">${t(local?'forecastPublicLedgerLink':'allQuantiles')} ↗</a>`:''}</div>
    <p class="sr-only" data-forecast-announcement aria-live="polite" aria-atomic="true"></p><script type="application/json" data-forecast-data>${json}</script></section>`;
}
