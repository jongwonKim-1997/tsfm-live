import assert from 'node:assert/strict';
import test from 'node:test';
import {onRequestGet} from '../functions/api/v1/local_dashboard.json.js';

const snapshot = {frequency:'1h', mode:'local_zero_shot', public_ledger_eligible:false,
  indicators:[{public_export:true,license_id:'CC-BY-NC-4.0',source_status:{source_id:'coinmetrics_hourly'}}]};
test('KV snapshot is served with bounded cache and JSON headers', async () => {
  const result = await onRequestGet({env:{TSFM_DASHBOARD:{get:async key => {
    assert.equal(key,'hourly-dashboard'); return JSON.stringify(snapshot);
  }}}});
  assert.equal(result.status,200);
  assert.match(result.headers.get('Content-Type'),/application\/json/);
  assert.deepEqual(await result.json(),snapshot);
});
test('unconfigured binding falls through to static snapshot', async () => {
  const fallback = new Response('static');
  assert.equal(await onRequestGet({env:{},next:async()=>fallback}),fallback);
});
test('private values and failed KV reads are never served', async () => {
  const privateSnapshot=structuredClone(snapshot);
  privateSnapshot.indicators[0].source_status.source_id='upbit_hourly';
  for (const get of [async()=>JSON.stringify(privateSnapshot), async()=>{throw Error('failed');}]) {
    assert.equal((await onRequestGet({env:{TSFM_DASHBOARD:{get}}})).status,503);
  }
});
