// Optional KV binding keeps hourly data updates independent of site rebuilds.
export async function onRequestGet(context) {
  if (!context.env.TSFM_DASHBOARD) return context.next();
  try {
    const body = await context.env.TSFM_DASHBOARD.get('hourly-dashboard');
    if (!body) return context.next();
    const value = JSON.parse(body);
    if (value.frequency !== '1h' || value.mode !== 'local_zero_shot'
        || value.public_ledger_eligible !== false || !Array.isArray(value.indicators)
        || value.indicators.some(row => row.public_export !== true
          || row.license_id !== 'CC-BY-NC-4.0'
          || row.source_status?.source_id !== 'coinmetrics_hourly')) {
      return new Response('Invalid dashboard', {status: 503});
    }
    return new Response(body, {headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=60, s-maxage=60',
      'X-Content-Type-Options': 'nosniff',
    }});
  } catch {
    return new Response('Dashboard temporarily unavailable', {status: 503});
  }
}
