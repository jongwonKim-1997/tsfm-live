import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {JSDOM,VirtualConsole} from 'jsdom';
import {renderDashboardDocument} from '../src/lib/local-dashboard.mjs';
import {dashboardBoardMarkup,newerDashboardSnapshot} from '../src/lib/dashboard-view.mjs';
import {sourceAttributionMarkup} from '../src/lib/forecast-view.mjs';
const words=JSON.parse(fs.readFileSync(new URL('../src/i18n/ko.json',import.meta.url),'utf8'));
const anchor=Date.parse('2026-10-11T08:00:00Z'),hour=3600000,now=anchor+10*60000;
const history=Array.from({length:168},(_,index)=>{const ts=anchor-(167-index)*hour;return {close_ts:new Date(ts).toISOString(),session_date:new Date(ts+9*hour).toISOString().slice(0,10),value:100+index*.1,origin:'actual'};});
const path=Array.from({length:24},(_,index)=>({close_ts:new Date(anchor+(index+1)*hour).toISOString(),lower:116,median:117+index*.1,upper:120}));
const entrant={id:'model-a',name:'Model A',kind:'tsfm',status:'ok',availability:'available',next_close_ts:path[0].close_ts,path};
const indicator={id:'btc-usd',name:'BTC/USD',unit:'USD',decimals:2,enabled:true,visible:true,frequency:'1h',status:'available',market_status:'open',source_status:{freshness:'fresh'},source_name:'Coin Metrics Community Data',source_url:'https://docs.coinmetrics.io/packages/coin-metrics-community-data',license_id:'CC-BY-NC-4.0',license_url:'https://creativecommons.org/licenses/by-nc/4.0/',observation_kind:'reference_rate',context_length:169,last_observation:history.at(-1),history:{today:history.filter(row=>row.session_date==='2026-10-11'),last7days:history},entrants:[entrant]};
const base={mode:'local_zero_shot',inference_mode:'zero_shot',public_ledger_eligible:false,frequency:'1h',horizon_steps:24,run_ts_utc:'2026-10-11T08:05:00Z',generated_ts_utc:'2026-10-11T08:06:00Z',forecast_generated_ts_utc:'2026-10-11T08:06:00Z',indicators:[]};
const fresh={...base,run_ts_utc:'2026-10-11T08:07:00Z',generated_ts_utc:'2026-10-11T08:08:00Z',forecast_generated_ts_utc:'2026-10-11T08:08:00Z',indicators:[indicator,{...indicator,id:'eth-usd',name:'ETH/USD'}]};
const settle=()=>new Promise(resolve=>setImmediate(resolve));

test('reference rates show linked attribution, noncommercial licence, formatting and generated-output distinction',()=>{
  const dom=new JSDOM(dashboardBoardMarkup(fresh,'ko',words,{now}));
  const d=dom.window.document;
  assert.equal(d.querySelector('.forecast-source-attribution a').href,indicator.source_url);
  assert.equal(d.querySelectorAll('.forecast-source-attribution a')[1].href,indicator.license_url);
  assert.match(d.querySelector('.forecast-source-attribution').textContent,/CC BY-NC 4\.0.*비상업용/);
  assert.match(d.querySelector('.forecast-source-attribution').textContent,/KST.*반올림.*TSFM Live/);
  assert.match(d.querySelector('.forecast-panel-heading').textContent,/정각 기준가격/);
  assert.match(d.querySelector('.forecast-context-note').textContent,/169/);
  const hostile=new JSDOM(sourceAttributionMarkup({...indicator,source_url:'javascript:alert(1)',license_url:'data:text/html,<script>alert(1)</script>',source_name:'<img src=x onerror=alert(1)>'},words)).window.document;
  assert.equal(hostile.querySelectorAll('a,img,script').length,0);
});

test('only valid newer snapshots with a nondecreasing execution time are accepted',()=>{
  assert.equal(newerDashboardSnapshot(fresh,base,now),true);
  for(const change of [{generated_ts_utc:base.generated_ts_utc},{run_ts_utc:'2026-10-11T08:04:00Z'},{frequency:'1d'},{mode:'other'},{indicators:[{...indicator,entrants:[null]}]}]){
    assert.equal(newerDashboardSnapshot({...fresh,...change},base,now),false);
  }
});

test('public polling adds fresh data to an empty page, preserves controls, ignores old data and expires on failure',async()=>{
  let clock=now,next=fresh,fail=false;
  const callbacks=[],calls=[],errors=[];
  const virtualConsole=new VirtualConsole();virtualConsole.on('jsdomError',error=>errors.push(error));
  const html=renderDashboardDocument(base,{now}).replace('data-dashboard-refresh="off"','data-dashboard-refresh="public"');
  const dom=new JSDOM(html,{url:'https://tsfm-live.pages.dev/ko/',runScripts:'dangerously',virtualConsole,beforeParse(window){
    window.Date=class extends Date {constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;}};
    window.setInterval=(callback,delay)=>{callbacks.push({callback,delay});return callbacks.length;};
    window.clearInterval=()=>{};
    window.fetch=async(url,options)=>{calls.push({url,options});if(fail)throw new Error('offline');return {ok:true,json:async()=>structuredClone(next)};};
  }});
  try{
    await settle();
    const d=dom.window.document;
    assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/v1/local_dashboard.json');
    assert.equal(calls[0].options.cache,'no-store');assert.equal(calls[0].options.credentials,'omit');
    assert.equal(callbacks[0].delay,60000);
    assert.equal(d.querySelectorAll('.forecast-model-line').length,1);
    const select=d.querySelector('[data-indicator-select]');select.value='eth-usd';select.dispatchEvent(new dom.window.Event('change',{bubbles:true}));
    d.querySelector('[data-history-period="last7days"]').click();d.querySelector('[data-highlight-model="model-a"]').click();
    clock=anchor+12*60000;
    next={...fresh,run_ts_utc:'2026-10-11T08:09:00Z',generated_ts_utc:'2026-10-11T08:10:00Z'};
    callbacks[0].callback();await settle();
    assert.equal(d.querySelector('.forecast-instrument-title h2').textContent,'ETH/USD');
    assert.equal(d.querySelectorAll('.forecast-observation').length,168);
    assert.equal(d.querySelector('.forecast-mark.is-focused').dataset.forecastMark,'model-a');
    next=fresh;callbacks[0].callback();await settle();
    assert.equal(JSON.parse(d.querySelector('[data-forecast-data]').textContent).generated_ts_utc,'2026-10-11T08:10:00Z');
    clock=anchor+75*60000;fail=true;callbacks[0].callback();await settle();
    assert.equal(d.querySelectorAll('.forecast-observation,.forecast-model-line').length,0);
    assert.ok(d.querySelector('.forecast-empty'));assert.deepEqual(errors,[]);
  }finally{dom.window.close();}
});

test('standalone reports never fetch public snapshots, including file URLs',async()=>{
  for(const url of ['file:///tmp/tsfm-report.html','https://example.test/local-report.html']){
    let calls=0;
    const dom=new JSDOM(renderDashboardDocument(fresh,{now}),{url,runScripts:'dangerously',beforeParse(window){window.fetch=async()=>{calls++;throw new Error('must not fetch');};}});
    try{await settle();assert.equal(calls,0);assert.equal(dom.window.document.querySelector('meta[http-equiv="refresh"]').content,'300');}
    finally{dom.window.close();}
  }
});
