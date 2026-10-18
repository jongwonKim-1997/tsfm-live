import test from 'node:test';
import assert from 'node:assert/strict';
import {dailyPerformance,performanceMarkup,settledDaily,MIN_RANK_TARGETS} from '../src/lib/daily-performance.mjs';
import {dailyMarkup} from '../src/lib/daily-view.mjs';

const now=Date.parse('2026-10-18T18:00:00Z');
const actual={date:'2026-10-16',close_ts:'2026-10-16T14:00:00Z',value:102};
const forecast=(model='chronos-2',median=101)=>({model_id:model,issue_date:'2026-10-15',issued_at:'2026-10-15T16:00:00Z',anchor:{date:'2026-10-15',close_ts:'2026-10-15T14:00:00Z',value:100},points:[{date:actual.date,close_ts:actual.close_ts,median,lower:99,upper:103}]});
const row=(issues=[],history=[actual])=>({id:'test',name:'Test index',unit:'points',group:'equity',history,forecast_history:issues,forecasts:[],previous_forecasts:[]});
const data=indicators=>({schema_version:'daily-public-v1',frequency:'1d',date:'2026-10-18',generated_ts_utc:new Date(now).toISOString(),indicators});

test('unsettled forecasts show no probability, score or rank, not zero percent success',()=>{
  const r=row([forecast()]);r.history=[];
  const stats=dailyPerformance(data([r]),now);
  assert.equal(stats.indicators[0].models[0].n,0);
  assert.equal(stats.indicators[0].models[0].direction,null);
  assert.equal(stats.ranking[0].rank,null);
  const html=performanceMarkup(data([r]),{now});
  assert.match(html,/미래 성공 확률이 아닙니다/);
  assert.match(html,/평가 대기/);
  assert.doesNotMatch(html,/NaN|Infinity|0\.0%/);
  assert.match(dailyMarkup(data([r]),{now}),/매시간 갱신은 수집·업로드 주기/);
});

test('scores earliest genuine pre-target issue once despite refreshed or duplicated forecasts',()=>{
  const first=forecast(),later={...forecast('chronos-2',102),issued_at:'2026-10-16T10:00:00Z'};
  const r=row([later,first,first]);r.forecasts=[later];
  const m=dailyPerformance(data([r]),now).indicators[0].models[0];
  assert.equal(m.n,1);assert.equal(m.mae,1);assert.equal(m.direction,1);assert.equal(m.coverage,1);
  assert.equal(m.skill,.5);
});

test('rejects late issues, unclosed anchors, invalid bounds and mismatched target timestamps',()=>{
  for(const invalid of [
    {...forecast(),issued_at:actual.close_ts},
    {...forecast(),issued_at:'invalid'},
    {...forecast(),anchor:{...forecast().anchor,close_ts:'2026-10-16T17:00:00Z'}},
    {...forecast(),points:[{...forecast().points[0],close_ts:'2026-10-16T15:00:00Z'}]},
    {...forecast(),points:[{...forecast().points[0],lower:104}]},
  ])assert.equal(settledDaily(row([invalid]),now).get('chronos-2').size,0);
  assert.equal(settledDaily(row([forecast()]),Date.parse('2026-10-16T13:00:00Z')).get('chronos-2').size,0);
  const snapshot=data([row([forecast()])]);snapshot.generated_ts_utc='2026-10-16T13:00:00Z';
  assert.equal(dailyPerformance(snapshot,now).indicators[0].models[0].n,0);
});

test('unchanged actuals are excluded from direction denominator, unchanged forecasts are misses when actual moves',()=>{
  let m=dailyPerformance(data([row([forecast('chronos-2',100)])]),now).indicators[0].models[0];
  assert.equal(m.direction,0);assert.equal(m.directionN,1);
  m=dailyPerformance(data([row([forecast()], [{...actual,value:100}])]),now).indicators[0].models[0];
  assert.equal(m.n,1);assert.equal(m.direction,null);assert.equal(m.directionN,0);assert.equal(m.skill,null);
});

test('ranking requires matched issue day and input anchor',()=>{
  for(const other of [{...forecast('chronos-bolt-base'),issue_date:'2026-10-16'}, {...forecast('chronos-bolt-base'),anchor:{...forecast().anchor,value:99}}]){
    const stats=dailyPerformance(data([row([forecast(),other])]),now);
    assert.equal(stats.indicators[0].models[1].n,1);
    assert.equal(stats.ranking[0].n,0);
    assert.equal(stats.ranking[0].rank,null);
  }
});

function series(id,count,multiplier=1,flat=false){
  const issues=[],history=[];
  for(let i=0;i<count;i++){
    const anchorDay=new Date(Date.UTC(2026,8,20+i)).toISOString().slice(0,10);
    const targetDay=new Date(Date.UTC(2026,8,21+i)).toISOString().slice(0,10);
    history.push({date:targetDay,close_ts:targetDay+'T14:00:00Z',value:(flat?100:102)*multiplier});
    for(const [id,median] of [['chronos-2',101],['chronos-bolt-base',99]])issues.push({model_id:id,issue_date:anchorDay,issued_at:anchorDay+'T16:00:00Z',anchor:{date:anchorDay,close_ts:anchorDay+'T14:00:00Z',value:100*multiplier},points:[{date:targetDay,close_ts:targetDay+'T14:00:00Z',median:median*multiplier,lower:98*multiplier,upper:103*multiplier}]});
  }
  return {...row(issues,history),id};
}

test('ranks paired baseline-relative errors across equally weighted indicators only after threshold',()=>{
  let stats=dailyPerformance(data([series('a',MIN_RANK_TARGETS),series('b',MIN_RANK_TARGETS,1000)]),now);
  assert.equal(stats.rankReady,true);
  assert.deepEqual(stats.ranking.map(m=>[m.id,m.rank,m.skill]),[['chronos-2',1,.5],['chronos-bolt-base',2,-.5]]);
  assert.equal(stats.ranking[0].n,40);
  stats=dailyPerformance(data([series('a',20),series('b',19)]),now);
  assert.equal(stats.rankReady,false);assert.equal(stats.ranking[0].rank,null);assert.equal(stats.ranking[0].eligibleIndicators,1);
  stats=dailyPerformance(data([series('a',20),series('b',20,1,true)]),now);
  assert.equal(stats.rankReady,false);assert.equal(stats.ranking[0].skill,null);
});

test('ranking ties share rank and metric labels escape source text',()=>{
  const r=series('a',20);
  r.forecast_history.forEach(f=>{f.points[0].median=101;});
  assert.deepEqual(dailyPerformance(data([r]),now).ranking.map(m=>m.rank),[1,1]);
  const html=performanceMarkup(data([{...r,id:'<script>',unit:'<img>'}]),{now});
  assert.doesNotMatch(html,/<script>|<img>/);
  assert.match(performanceMarkup(data([r]),{now,locale:'en'}),/not future success probabilities/);
});
