export async function onRequestGet(context) {
  if (!context.env.TSFM_DASHBOARD) return context.next();
  try {
    const body = await context.env.TSFM_DASHBOARD.get('daily-dashboard');
    if (!body) return context.next();
    if (new TextEncoder().encode(body).length > 2_000_000) return new Response('Invalid daily dashboard', {status:503});
    const data = JSON.parse(body);
    const sources = {eurusd:'ecb',usdjpy:'ecb','ecb-usdkrw':'ecb',ust2y:'ustreasury',ust10y:'ustreasury',taiex:'twse_open'};
    const licenses = {ecb:'ECB-reuse',ustreasury:'US-government-work',twse_open:'OGDL-Taiwan-1.0'};
    function privateField(value) {
      if (Array.isArray(value)) return value.some(privateField);
      if (!value || typeof value !== 'object') return false;
      return Object.entries(value).some(([key,item]) => /token|secret|password|api_key/i.test(key)
        || ['context','raw_evidence','raw_file','env_file','cache_dir','authorization'].includes(key.toLowerCase()) || privateField(item));
    }
    if (data.schema_version !== 'daily-public-v1' || data.frequency !== '1d'
      || !['1d','1h'].includes(data.issue_frequency || '1d')
      || data.device !== 'cuda' || data.input_basis !== 'own_daily_levels_only' || data.inference_mode !== 'zero_shot'
      || data.public_ledger_eligible !== false || !Array.isArray(data.indicators)
      || ![5,6].includes(data.indicators.length) || new Set(data.indicators.map(r => r.id)).size !== data.indicators.length || privateField(data)
      || ['eurusd','usdjpy','ecb-usdkrw','ust2y','ust10y'].some(id=>!data.indicators.some(r=>r.id===id))
      || data.indicators.some(r => r.public_export !== true || !Object.hasOwn(sources,r.id) || sources[r.id] !== r.source_id
        || r.license_id !== licenses[r.source_id]
        || ['forecasts','previous_forecasts','forecast_history'].some(key => !Array.isArray(r[key])
          || r[key].some(f => !['chronos-2','chronos-bolt-base','timesfm-2.5-200m','toto-open-base-1.0','timer-base-84m'].includes(f.model_id) || f.model_license !== 'apache-2.0')))) {
      return new Response('Invalid daily dashboard', {status:503});
    }
    return new Response(body, {headers:{'Content-Type':'application/json; charset=utf-8',
      'Cache-Control':'public, max-age=60, s-maxage=60', 'X-Content-Type-Options':'nosniff'}});
  } catch {
    return new Response('Daily dashboard temporarily unavailable', {status:503});
  }
}
