import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {JSDOM} from 'jsdom';
import {asViewed,chartMarkup,chooseIndicator,historyFor,panelMarkup,usableForecast,highlightForecast} from '../src/lib/forecast-view.mjs';
const words=JSON.parse(fs.readFileSync(new URL('../src/i18n/en.json',import.meta.url),'utf8'));
const model={id:'test-model',name:'Model A',kind:'tsfm',status:'ok',availability:'available',lower:0,median:1,upper:2,next_session_date:'2026-10-09',next_close_ts:'2026-10-09T16:00:00Z'};
const last={session_date:'2026-10-08',value:1,origin:'actual'};
const indicator={id:'fx',name:'EUR/USD',unit:'USD/EUR',decimals:4,enabled:true,status:'available',next_session_date:'2026-10-09',next_session_timezone:'Europe/Frankfurt',last_observation:last,history:{today:[last],last7days:[{session_date:'2026-10-02',value:0,origin:'actual'},last]},entrants:[model]};
const document=html=>new JSDOM(html).window.document;

test('history toggles actual points while the same target forecast remains unchanged',()=>{
  const today=document(chartMarkup(indicator,'today','en',words));
  const week=document(chartMarkup(indicator,'last7days','en',words));
  assert.equal(today.querySelectorAll('.forecast-observation').length,1);
  assert.equal(week.querySelectorAll('.forecast-observation').length,2);
  assert.equal(today.querySelectorAll('.forecast-mark').length,1);
  assert.equal(week.querySelectorAll('.forecast-mark').length,1);
  assert.match(week.querySelector('.forecast-mark title').textContent,/2026-10-09/);
  assert.equal(historyFor(indicator,'last7days')[0].value,0);
  const table=document(panelMarkup(indicator,'last7days','en',words)).querySelector('.forecast-actual-table');
  assert.equal(table.querySelectorAll('tbody tr').length,2);
  assert.match(table.textContent,/2026-10-02/);
  assert.match(table.textContent,/USD\/EUR/);
});
test('missing and disabled forecasts never invent numeric chart marks',()=>{
  const empty={...indicator,status:'unavailable',last_observation:null,history:{today:[],last7days:[]},entrants:[{...model,status:'missing',median:null,lower:null,upper:null}]};
  const html=panelMarkup(empty,'today','en',words,350), doc=document(html);
  assert.equal(doc.querySelectorAll('.forecast-mark,.forecast-observation').length,0);
  assert.match(doc.body.textContent,/Awaiting forecasts/);
  assert.doesNotMatch(html,/NaN|Infinity|undefined/);
  assert.equal(usableForecast({...model,availability:'disabled'}),false);
  assert.equal(usableForecast({...model,availability:'unavailable'}),false);
  assert.equal(usableForecast({...model,status:'void'}),false);
  assert.equal(usableForecast({...model,lower:3}),false);
});
test('zero-width intervals remain finite and zero medians are visible',()=>{
  const exact={...indicator,entrants:[{...model,lower:0,median:0,upper:0}],last_observation:{...last,value:0},history:{today:[{...last,value:0}]}};
  const html=panelMarkup(exact,'today','en',words,320);
  assert.doesNotMatch(html,/NaN|Infinity/);
  assert.equal(document(html).querySelectorAll('.forecast-mark').length,1);
  assert.match(document(html).querySelector('.forecast-model-value').textContent,/0\.00/);
});
test('stale static data expires at page view without changing recorded numbers',()=>{
  const viewed=asViewed(indicator,Date.parse('2026-10-09T16:00:00Z'));
  assert.equal(viewed.status,'expired');
  assert.equal(viewed.entrants[0].availability,'expired');
  assert.equal(viewed.entrants[0].median,model.median);
  assert.equal(indicator.status,'available');
  assert.equal(indicator.entrants[0].availability,'available');
  const html=panelMarkup(viewed,'today','en',words);
  assert.match(document(html).body.textContent,/Past session/);
  assert.equal(document(html).querySelectorAll('.forecast-expired').length,1);
});
test('display units and exact session timezone are retained and text cannot inject markup',()=>{
  const row={...indicator,name:'<img src=x onerror=alert(1)>',unit:'%',unit_label:'yield (%)',entrants:[{...model,name:'<script>alert(1)</script>'}]};
  const doc=document(panelMarkup(row,'today','en',words));
  assert.equal(doc.querySelectorAll('img,script').length,0);
  assert.match(doc.body.textContent,/yield \(%\)/);
  assert.match(doc.body.textContent,/Europe\/Frankfurt/);
  assert.match(doc.body.textContent,/2026-10-09/);
});
test('default selection prefers active evidence and duplicate daily points do not divide by zero',()=>{
  assert.equal(chooseIndicator([{...indicator,id:'disabled',enabled:false,status:'disabled',entrants:[]},indicator]).id,'fx');
  const duplicate={...indicator,history:{last7days:[last,last]}};
  assert.equal(historyFor(duplicate,'last7days').length,1);
  assert.doesNotMatch(chartMarkup(duplicate,'last7days','en',words),/NaN/);
});
test('forecast lines use date coordinates: equal targets align and later sessions move right',()=>{
  const actual={...last,close_ts:'2026-10-08T16:00:00Z'};
  const rows=[model,{...model,id:'second',median:1.5},
    {...model,id:'later',median:.5,next_close_ts:'2026-10-10T16:00:00Z',next_session_date:'2026-10-10'}];
  const doc=document(chartMarkup({...indicator,history:{today:[actual]},entrants:rows},'today','en',words));
  const marks=[...doc.querySelectorAll('.forecast-mark')];
  const endpoints=marks.map(mark=>Number(mark.querySelector('.forecast-endpoint').getAttribute('cx')));
  assert.equal(marks.length,3);
  assert.equal(endpoints[0],endpoints[1]);
  assert.ok(endpoints[2]>endpoints[0]);
  const paths=marks.map(mark=>mark.querySelector('.forecast-model-line').getAttribute('d'));
  const starts=paths.map(path=>path.match(/^M([^ ]+)/)[1]);
  assert.equal(new Set(starts).size,1);
  const actualX=Number(starts[0].split(',')[0]);
  assert.ok(Math.abs((endpoints[2]-actualX)/(endpoints[0]-actualX)-2)<1e-10);
  assert.ok([...doc.querySelectorAll('.forecast-date-tick')].every(tick=>/^\d{2}\/\d{2}$/.test(tick.textContent)));
  assert.equal(doc.querySelectorAll('.forecast-mark rect').length,0);
});
test('the history line joins only actual observations and model highlight is reversible',()=>{
  const doc=document(panelMarkup({...indicator,entrants:[model,{...model,id:'second',median:1.5}]},'last7days','en',words));
  assert.ok(doc.querySelector('.forecast-actual-line'));
  assert.equal(doc.querySelectorAll('.forecast-model-line').length,2);
  highlightForecast(doc,'second');
  assert.equal(doc.querySelectorAll('.forecast-mark.is-focused').length,1);
  assert.equal(doc.querySelector('.forecast-mark.is-focused').dataset.forecastMark,'second');
  assert.equal(doc.querySelectorAll('.forecast-mark.is-dim').length,1);
  highlightForecast(doc,null);
  assert.equal(doc.querySelectorAll('.is-focused,.is-dim').length,0);
});
