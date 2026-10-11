import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {JSDOM,VirtualConsole} from 'jsdom';
import {chooseDashboardData,dashboardBoardMarkup,prepareDashboard,validLocalDashboard} from '../src/lib/dashboard-view.mjs';
import {renderDashboardDocument} from '../src/lib/local-dashboard.mjs';
const words=JSON.parse(fs.readFileSync(new URL('../src/i18n/ko.json',import.meta.url),'utf8'));
const now=Date.parse('2026-10-11T08:00:00Z');
const actuals=[5,6,7,8,9].map((day,index)=>({session_date:`2026-10-${String(day).padStart(2,'0')}`,close_ts:`2026-10-${String(day).padStart(2,'0')}T14:00:00Z`,value:1.16+index*.001,origin:'actual'}));
const entrant={id:'model-one',name:'Model One',kind:'tsfm',status:'ok',availability:'available',lower:1.15,median:1.17,upper:1.19,next_session_date:'2026-10-12',next_close_ts:'2026-10-12T14:00:00Z'};
const indicator={id:'eurusd',name:'EUR/USD',unit:'USD/EUR',decimals:4,enabled:true,status:'available',next_session_date:'2026-10-12',next_session_timezone:'Europe/Frankfurt',last_observation:actuals.at(-1),forecast_anchor:actuals.at(-1),history:{today:[actuals.at(-1)],last7days:actuals},entrants:[entrant,{...entrant,id:'model-two',name:'Model Two',median:1.16}]};
const snapshot={mode:'local_zero_shot',inference_mode:'zero_shot',public_ledger_eligible:false,run_ts_utc:'2026-10-11T06:00:00Z',collection_ts_utc:'2026-10-11T06:00:00Z',forecast_generated_ts_utc:'2026-10-11T06:04:00Z',generated_ts_utc:'2026-10-11T06:04:00Z',indicators:[indicator]};
const document=html=>new JSDOM(html).window.document;

test('local snapshots require explicit zero-shot provenance and valid timestamps',()=>{
  const ledger={run_ts_utc:null,indicators:[]};
  assert.equal(validLocalDashboard(snapshot,now),true);
  assert.equal(chooseDashboardData(snapshot,ledger,now),snapshot);
  for(const change of [{mode:'other'},{inference_mode:'trained'},{public_ledger_eligible:true},{run_ts_utc:null},{generated_ts_utc:'2026-10-13T00:00:00Z'},{indicators:[{...indicator,history:{today:[{session_date:'2026-10-09',value:1}],last7days:[]}}]}]){
    assert.equal(chooseDashboardData({...snapshot,...change},ledger,now),ledger);
  }
  const newer={run_ts_utc:'2026-10-11T07:00:00Z',indicators:[indicator]};
  assert.equal(chooseDashboardData(snapshot,newer,now),newer);
});

test('first screen contains an actual line without requiring any successful prediction',()=>{
  const data={...snapshot,indicators:[{...indicator,status:'unavailable',entrants:[{...entrant,status:'failed',availability:'unavailable',lower:null,median:null,upper:null}]}]};
  const doc=document(dashboardBoardMarkup(data,'ko',words,{now}));
  assert.equal(doc.querySelectorAll('.forecast-actual-line').length,1);
  assert.equal(doc.querySelectorAll('.forecast-observation').length,5);
  assert.equal(doc.querySelectorAll('.forecast-model-line').length,0);
  assert.equal(doc.querySelector('[data-history-period="last7days"]').getAttribute('aria-pressed'),'true');
  assert.match(doc.querySelector('.forecast-panel-heading').textContent,/2026-10-09/);
  assert.match(doc.querySelector('[data-dashboard-provenance]').textContent,/2026\. 10\. 11\./);
  assert.match(doc.querySelector('[data-dashboard-provenance]').textContent,/공개 사전 고정 원장/);
});

test('local outputs beyond their target retain values but visibly expire',()=>{
  const late=Date.parse('2026-10-13T08:00:00Z');
  const doc=document(dashboardBoardMarkup(snapshot,'ko',words,{now:late}));
  assert.equal(doc.querySelectorAll('.forecast-expired').length,2);
  assert.match(doc.querySelector('.forecast-state').textContent,/지난 거래일/);
  assert.match(doc.querySelector('[data-dashboard-provenance]').textContent,/36시간/);
  assert.equal(doc.querySelectorAll('.forecast-actual-line').length,1);
});

test('a target at or before the observed input or inference time is never drawn',()=>{
  for(const target of ['2026-10-09T14:00:00Z','2026-10-11T05:00:00Z']){
    const data={...snapshot,indicators:[{...indicator,entrants:[{...entrant,next_close_ts:target}]}]};
    const prepared=prepareDashboard(data,now);
    assert.equal(prepared.indicators[0].entrants[0].availability,'unavailable');
    const doc=document(dashboardBoardMarkup(data,'ko',words,{now}));
    assert.equal(doc.querySelectorAll('.forecast-model-line').length,0);
    assert.equal(doc.querySelectorAll('.forecast-actual-line').length,1);
  }
});

test('observations-only snapshots never invent a collection or inference timestamp',()=>{
  const data={...snapshot,collection_ts_utc:null,forecast_generated_ts_utc:null,indicators:[{...indicator,collection_ts_utc:null,forecast_generated_ts_utc:null,status:'unavailable',entrants:[]}]};
  const prepared=prepareDashboard(data,now);
  assert.equal(prepared.indicators[0].forecast_generated_ts_utc,null);
  assert.equal(prepared.indicators[0].collection_ts_utc,null);
  const doc=document(dashboardBoardMarkup(data,'ko',words,{now}));
  assert.equal(doc.querySelector('.forecast-computation-note'),null);
  assert.equal(doc.querySelector('[data-dashboard-provenance] time').textContent,'—');
  assert.equal(doc.querySelectorAll('.forecast-actual-line').length,1);
});

test('standalone offline report executes the same controls and escapes embedded data',()=>{
  const data={...snapshot,indicators:[{...indicator,name:'EUR/USD </script><img src=x onerror=alert(1)>'},{...indicator,id:'usd-jpy',name:'USD/JPY'}]};
  const errors=[],console=new VirtualConsole();console.on('jsdomError',error=>errors.push(error));
  const dom=new JSDOM(renderDashboardDocument(data,{now}),{runScripts:'dangerously',virtualConsole:console});
  try{
    const doc=dom.window.document;
    assert.deepEqual(errors,[]);
    assert.equal(doc.querySelectorAll('img,script[src],link[href]').length,0);
    assert.match(doc.querySelector('.forecast-local-licence').textContent,/Built with technology from NXAI/);
    assert.match(doc.querySelector('.forecast-local-licence pre').textContent,/NXAI COMMUNITY LICENSE AGREEMENT/);
    assert.equal(doc.querySelectorAll('.forecast-actual-line').length,1);
    assert.equal(doc.querySelectorAll('.forecast-model-line').length,2);
    doc.querySelector('[data-history-period="today"]').click();
    assert.equal(doc.querySelectorAll('.forecast-observation').length,1);
    assert.equal(doc.querySelectorAll('.forecast-model-line').length,2);
    assert.match(doc.querySelector('.forecast-footnote').textContent,/한 개이면 점/);
    doc.querySelector('[data-highlight-model="model-two"]').click();
    assert.equal(doc.querySelector('.forecast-mark.is-focused').dataset.forecastMark,'model-two');
    doc.querySelector('[data-history-period="last7days"]').click();
    assert.equal(doc.querySelectorAll('.forecast-observation').length,5);
    doc.querySelector('[data-indicator="usd-jpy"]').click();
    assert.equal(doc.querySelector('.forecast-instrument-title h2').textContent,'USD/JPY');
    assert.deepEqual(errors,[]);
  }finally{dom.window.close();}
});
