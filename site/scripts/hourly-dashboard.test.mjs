import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {JSDOM,VirtualConsole} from 'jsdom';
import {asViewed,chartMarkup,historyFor} from '../src/lib/forecast-view.mjs';
import {chooseDashboardData,dashboardBoardMarkup,dashboardWords,prepareDashboard,validLocalDashboard} from '../src/lib/dashboard-view.mjs';
import {renderDashboardDocument} from '../src/lib/local-dashboard.mjs';
const words=JSON.parse(fs.readFileSync(new URL('../src/i18n/ko.json',import.meta.url),'utf8'));
const hourlyWords=dashboardWords(words,true,true);
const anchor=Date.parse('2026-10-11T08:00:00Z'),now=anchor+15*60000,hour=3600000;
const point=(time,value)=>({close_ts:new Date(time).toISOString(),session_date:new Date(time+9*hour).toISOString().slice(0,10),value,origin:'actual'});
const history=Array.from({length:168},(_,index)=>point(anchor-(167-index)*hour,100+index*.01));
const path=Array.from({length:24},(_,index)=>({close_ts:new Date(anchor+(index+1)*hour).toISOString(),median:102+index*.05,lower:101+index*.04,upper:103+index*.06}));
const model={id:'model-one',name:'Model One',kind:'tsfm',status:'ok',availability:'available',next_close_ts:path[0].close_ts,path};
const instrument={id:'btc-krw',name:'BTC/KRW',unit:'KRW',decimals:2,enabled:true,visible:true,market_status:'open',frequency:'1h',status:'available',source_status:{freshness:'fresh'},last_observation:history.at(-1),history:{today:history.filter(row=>row.session_date==='2026-10-11'),last7days:history},entrants:[model,{...model,id:'model-two',name:'Model Two'}]};
const snapshot={mode:'local_zero_shot',inference_mode:'zero_shot',frequency:'1h',horizon_steps:24,public_ledger_eligible:false,run_ts_utc:'2026-10-11T08:05:00Z',collection_ts_utc:'2026-10-11T08:05:00Z',forecast_generated_ts_utc:'2026-10-11T08:14:00Z',generated_ts_utc:'2026-10-11T08:14:00Z',indicators:[instrument]};
const doc=html=>new JSDOM(html).window.document;

test('same-day hourly observations keep timestamp identity and all 24 forecast steps',()=>{
  assert.equal(historyFor(instrument,'today').length,18);
  assert.equal(historyFor({...instrument,history:{today:[...instrument.history.today,instrument.history.today[0]]}},'today').length,18);
  const today=doc(chartMarkup(instrument,'today','ko',hourlyWords));
  const week=doc(chartMarkup(instrument,'last7days','ko',hourlyWords));
  assert.equal(today.querySelectorAll('.forecast-observation').length,18);
  assert.equal(week.querySelectorAll('.forecast-observation').length,168);
  for(const document of [today,week]){
    assert.equal(document.querySelectorAll('.forecast-endpoint').length,48);
    assert.equal(document.querySelectorAll('.forecast-model-line').length,2);
    assert.equal((document.querySelector('.forecast-model-line').getAttribute('d').match(/L/g)||[]).length,24);
    assert.equal(document.querySelector('.forecast-endpoint').dataset.targetTs,path[0].close_ts);
    assert.equal([...document.querySelectorAll('.forecast-endpoint')].at(-1).dataset.targetTs,path.at(-1).close_ts);
    assert.match(document.querySelector('.forecast-date-tick').textContent,/\d{2}\/\d{2} \d{2}:00/);
    assert.match(document.querySelector('.forecast-observation title').textContent,/KST/);
  }
});

test('empty hourly snapshots never reveal a daily fallback',()=>{
  const empty={...snapshot,indicators:[],empty_reason:'public_hourly_source_pending'};
  const ledger={run_ts_utc:'2026-10-11T08:10:00Z',indicators:[{...instrument,entrants:[{...model,path:undefined,median:1,lower:0,upper:2}]}]};
  assert.equal(validLocalDashboard(empty,now),true);
  assert.equal(chooseDashboardData(empty,ledger,now),empty);
  const document=doc(dashboardBoardMarkup(empty,'ko',words,{now}));
  assert.equal(document.querySelectorAll('.forecast-model-line,.forecast-observation').length,0);
  assert.match(document.querySelector('.forecast-empty').textContent,/공개 가능한 시간별/);
});

test('closed, unknown, unavailable and stale sources disappear; fresh model failures retain actuals',()=>{
  for(const change of [{visible:false},{market_status:'closed'},{market_status:'unknown'},{market_status:'unavailable'},{source_status:{freshness:'source_lag'}}]){
    assert.equal(prepareDashboard({...snapshot,indicators:[{...instrument,...change}]},now).indicators.length,0);
  }
  assert.equal(prepareDashboard(snapshot,anchor+75*60000).indicators.length,0);
  assert.equal(prepareDashboard(snapshot,anchor+75*60000-1).indicators.length,1);
  const failed={...snapshot,indicators:[{...instrument,status:'unavailable',entrants:[{...model,status:'failed',availability:'unavailable',path:[]}]}]};
  const document=doc(dashboardBoardMarkup(failed,'ko',words,{now}));
  assert.equal(document.querySelectorAll('.forecast-actual-line').length,1);
  assert.equal(document.querySelectorAll('.forecast-model-line').length,0);
});

test('past hourly forecast points are removed without fabricating intermediate steps',()=>{
  const viewed=asViewed(instrument,anchor+hour+1);
  assert.equal(viewed.entrants[0].path.length,23);
  assert.equal(viewed.entrants[0].path[0].close_ts,path[1].close_ts);
  const bad={...snapshot,indicators:[{...instrument,entrants:[{...model,path:[path[0],...path.slice(2)]}]}]};
  const document=doc(dashboardBoardMarkup(bad,'ko',words,{now}));
  assert.equal(document.querySelectorAll('.forecast-model-line').length,0);
  const gap={...instrument,history:{today:[history[0],history[2]]}};
  const line=doc(chartMarkup(gap,'today','ko',hourlyWords)).querySelector('.forecast-actual-line').getAttribute('d');
  assert.equal((line.match(/M/g)||[]).length,2);
});

test('hourly standalone controls, 5-minute refresh and display-time stale hiding execute offline',()=>{
  let clock=now;
  const errors=[],virtualConsole=new VirtualConsole();virtualConsole.on('jsdomError',error=>errors.push(error));
  const dom=new JSDOM(renderDashboardDocument(snapshot,{now}),{runScripts:'dangerously',virtualConsole,beforeParse(window){
    window.Date=class extends Date {constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;}};
  }});
  try{
    const document=dom.window.document;
    assert.deepEqual(errors,[]);
    assert.equal(document.querySelector('meta[http-equiv="refresh"]').content,'300');
    assert.equal(document.querySelector('[data-history-period="today"]').getAttribute('aria-pressed'),'true');
    assert.equal(document.querySelectorAll('.forecast-observation').length,18);
    document.querySelector('[data-history-period="last7days"]').click();
    assert.equal(document.querySelectorAll('.forecast-observation').length,168);
    assert.equal(document.querySelectorAll('.forecast-endpoint').length,48);
    clock=anchor+hour+1;
    document.querySelector('[data-history-period="today"]').click();
    assert.equal(document.querySelectorAll('.forecast-endpoint').length,46);
    clock=anchor+75*60000;
    document.querySelector('[data-history-period="last7days"]').click();
    assert.equal(document.querySelectorAll('.forecast-observation,.forecast-endpoint').length,0);
    assert.ok(document.querySelector('.forecast-empty'));
    assert.equal(document.querySelector('.forecast-market-bar'),null);
    assert.deepEqual(errors,[]);
  }finally{dom.window.close();}
});

test('a report rendered during the first-hour grace retains raw 24-step input and 23 future steps',()=>{
  const viewedAt=anchor+hour+60000;
  const first=prepareDashboard(snapshot,viewedAt),second=prepareDashboard(snapshot,viewedAt);
  assert.deepEqual(first,second);
  assert.equal(first.indicators[0].entrants[0].path.length,23);
  assert.equal(snapshot.indicators[0].entrants[0].path.length,24);
  const html=renderDashboardDocument(snapshot,{now:viewedAt});
  const staticDocument=doc(html);
  const embedded=JSON.parse(staticDocument.querySelector('[data-forecast-data]').textContent);
  assert.equal(embedded.indicators[0].entrants[0].path.length,24);
  assert.equal(staticDocument.querySelectorAll('.forecast-endpoint').length,46);
  const errors=[],virtualConsole=new VirtualConsole();virtualConsole.on('jsdomError',error=>errors.push(error));
  const dom=new JSDOM(html,{runScripts:'dangerously',virtualConsole,beforeParse(window){
    window.Date=class extends Date {constructor(...args){super(...(args.length?args:[viewedAt]));}static now(){return viewedAt;}};
  }});
  try{
    const document=dom.window.document;
    assert.deepEqual(errors,[]);
    assert.equal(document.querySelectorAll('.forecast-model-line').length,2);
    assert.equal(document.querySelectorAll('.forecast-endpoint').length,46);
    assert.equal(document.querySelector('.forecast-endpoint').dataset.targetTs,path[1].close_ts);
    document.querySelector('[data-history-period="last7days"]').click();
    assert.equal(document.querySelectorAll('.forecast-endpoint').length,46);
    assert.equal(document.querySelectorAll('.forecast-observation').length,168);
    assert.deepEqual(errors,[]);
  }finally{dom.window.close();}
});
