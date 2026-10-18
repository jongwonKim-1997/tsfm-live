import test from 'node:test';
import assert from 'node:assert/strict';
import {dailyMarkup,dailyChart} from '../src/lib/daily-view.mjs';
import {onRequestGet} from '../functions/api/v1/daily_dashboard.json.js';

const row={id:'eurusd',name:'EUR/USD',unit:'USD/EUR',group:'fx',history:[{date:'2026-10-16',value:1.2}],forecasts:[],previous_forecasts:[],today_actual:null,actual_status:'market_closed',license_id:'ECB-reuse',license_url:'https://www.ecb.europa.eu',attribution:'ECB',public_export:true};
const data={schema_version:'daily-public-v1',frequency:'1d',generated_ts_utc:'2026-10-18T09:00:00Z',date:'2026-10-18',public_ledger_eligible:false,indicators:[row]};
test('empty prior forecast is explicitly labelled; actual is not invented',()=>{
  const html=dailyMarkup(data,{now:Date.parse(data.generated_ts_utc)});
  assert.match(html,/어제 발행된 예측이 없습니다/);assert.match(html,/휴장/);
  assert.doesNotMatch(html,/NaN|Infinity/);
});
test('stale snapshot is visibly marked',()=>assert.match(dailyMarkup(data,{now:Date.parse(data.generated_ts_utc)+40*3600000}),/갱신이 지연/));
test('chart escapes labels and plots both frozen and newly issued values',()=>{
  const f={model_id:'chronos-2',anchor:{date:'2026-10-16',value:1.2},points:[{date:'2026-10-19',median:1.21,lower:1.19,upper:1.23}]};
  const html=dailyChart({...row,name:'<script>alert(1)</script>',forecasts:[f],previous_forecasts:[f]},data);
  assert.match(html,/<title>80%: 1.19 – 1.23<\/title>/);assert.match(html,/stroke-dasharray="7 5"/);assert.match(html,/#53a6ff/);assert.doesNotMatch(html,/<script>/);
});
test('KV fallback, valid payload and invalid source',async()=>{
  const payload={...data,device:'cuda',input_basis:'own_daily_levels_only',inference_mode:'zero_shot',indicators:['eurusd','usdjpy','ecb-usdkrw','ust2y','ust10y'].map(id=>({...row,id,source_id:id.startsWith('ust')?'ustreasury':'ecb',license_id:id.startsWith('ust')?'US-government-work':'ECB-reuse',forecast_history:[]}))};
  assert.equal(await onRequestGet({env:{},next:()=> 'fallback'}),'fallback');
  let response=await onRequestGet({env:{TSFM_DASHBOARD:{get:async()=>JSON.stringify(payload)}}});assert.equal(response.status,200);
  for(const invalid of [{...payload,indicators:payload.indicators.map(r=>({...r,license_id:'CC-BY-NC-4.0'}))},{...payload,api_token:'private'}]){
    response=await onRequestGet({env:{TSFM_DASHBOARD:{get:async()=>JSON.stringify(invalid)}}});assert.equal(response.status,503);
  }
});
