import {escapeHTML as esc} from './forecast-view.mjs';

export const DAILY_MODELS=[['chronos-2','Chronos-2'],['chronos-bolt-base','Chronos-Bolt'],['timesfm-2.5-200m','TimesFM 2.5'],['toto-open-base-1.0','Toto'],['timer-base-84m','Timer']];
export const MIN_RANK_TARGETS=20;
const mean=values=>values.length?values.reduce((a,b)=>a+b,0)/values.length:null;
const percent=value=>Number.isFinite(value)?`${(value*100).toFixed(1)}%`:'—';
const number=value=>Number.isFinite(value)?new Intl.NumberFormat('en-US',{maximumSignificantDigits:5}).format(value):'—';

// Score genuine pre-target issues, once per model and target. No backfilled issues.
export function settledDaily(row,asOf){
  const actuals=new Map((row.history||[]).filter(a=>Number.isFinite(a.value)&&Date.parse(a.close_ts)<=asOf).map(a=>[a.date,a]));
  const samples=new Map(DAILY_MODELS.map(([id])=>[id,new Map()]));
  const issues=[...(row.forecast_history||[]),...(row.previous_forecasts||[]),...(row.forecasts||[])].sort((a,b)=>Date.parse(a.issued_at)-Date.parse(b.issued_at));
  for(const f of issues){
    const issued=Date.parse(f.issued_at),anchor=f.anchor,byTarget=samples.get(f.model_id);
    if(!byTarget||!Number.isFinite(issued)||issued>asOf||!Number.isFinite(anchor?.value)||!Number.isFinite(Date.parse(anchor?.close_ts))||Date.parse(anchor.close_ts)>issued)continue;
    for(const p of f.points||[]){
      const actual=actuals.get(p.date),target=Date.parse(p.close_ts);
      const pointOnly=f.model_id==='timer-base-84m'&&p.forecast_type==='point'&&p.lower===null&&p.upper===null;
      const interval=[p.lower,p.upper].every(Number.isFinite)&&p.lower<=p.median&&p.median<=p.upper;
      if(!actual||byTarget.has(p.date)||!Number.isFinite(target)||issued>=target||target!==Date.parse(actual.close_ts)||!(p.date>anchor.date)||!Number.isFinite(p.median)||(!pointOnly&&!interval))continue;
      const delta=actual.value-anchor.value;
      byTarget.set(p.date,{date:p.date,issueDate:f.issue_date,anchorDate:anchor.date,anchorValue:anchor.value,anchorClose:anchor.close_ts,inputHash:f.input_sha256,inputCount:f.input_count,error:Math.abs(p.median-actual.value),baselineError:Math.abs(delta),direction:delta===0?null:Math.sign(p.median-anchor.value)===Math.sign(delta),covered:pointOnly?null:p.lower<=actual.value&&actual.value<=p.upper});
    }
  }
  return samples;
}

function summarize(samples){
  const directional=samples.filter(s=>s.direction!==null);
  const baseline=samples.reduce((sum,s)=>sum+s.baselineError,0);
  return {n:samples.length,directionN:directional.length,directionHits:directional.filter(s=>s.direction).length,direction:mean(directional.map(s=>Number(s.direction))),mae:mean(samples.map(s=>s.error)),coverage:mean(samples.filter(s=>s.covered!==null).map(s=>Number(s.covered))),skill:samples.length&&baseline>0?1-samples.reduce((sum,s)=>sum+s.error,0)/baseline:null};
}

export function dailyPerformance(data,now=Date.now()){
  const asOf=Math.min(now,Date.parse(data.generated_ts_utc));
  const indicators=(data.indicators||[]).map(row=>{
    const samples=settledDaily(row,asOf);
    const [left,...others]=DAILY_MODELS.map(([id])=>samples.get(id));
    const common=[...left.keys()].filter(date=>{
      const a=left.get(date);
      return others.every(group=>{const b=group.get(date);return b&&a.issueDate&&a.issueDate===b.issueDate&&a.anchorDate===b.anchorDate&&a.anchorValue===b.anchorValue&&a.anchorClose===b.anchorClose&&a.inputHash===b.inputHash&&a.inputCount===b.inputCount;});
    });
    return {id:row.id,name:row.name,unit:row.unit,commonN:common.length,models:DAILY_MODELS.map(([id,name])=>({id,name,...summarize([...samples.get(id).values()]),paired:summarize(common.map(date=>samples.get(id).get(date)))}))};
  });
  const eligible=indicators.filter(row=>row.commonN>=MIN_RANK_TARGETS&&row.models.every(m=>m.paired.skill!==null));
  const rankReady=indicators.length>0&&eligible.length===indicators.length;
  const ranking=DAILY_MODELS.map(([id,name])=>{
    const paired=indicators.map(row=>row.models.find(m=>m.id===id).paired);
    const allScorable=paired.length>0&&paired.every(p=>p.skill!==null);
    return {id,name,n:paired.reduce((sum,p)=>sum+p.n,0),eligibleIndicators:eligible.length,totalIndicators:indicators.length,skill:allScorable?mean(paired.map(p=>p.skill)):null,rank:null};
  });
  if(rankReady){
    ranking.sort((a,b)=>b.skill-a.skill);
    ranking.forEach((m,i)=>{m.rank=i&&Math.abs(m.skill-ranking[i-1].skill)<1e-10?ranking[i-1].rank:i+1;});
  }
  return {indicators,ranking,rankReady};
}

export function performanceMarkup(data,{locale='ko',now=Date.now()}={}){
  const ko=locale==='ko',stats=dailyPerformance(data,now);
  const title=ko?'지표별 예측 성과':'Forecast performance by indicator';
  const waiting=ko?'평가 대기':'Awaiting outcomes',early=ko?'표본 축적 중':'Accumulating samples';
  const headers=ko?['지표','모델','평가 건수','방향 적중률','평균 절대 오차','80% 구간 포함률','상태']:['Indicator','Model','Evaluated targets','Direction hit rate','Mean absolute error','80% interval coverage','Status'];
  const rows=stats.indicators.flatMap(row=>row.models.map(m=>`<tr><th scope="row">${esc(row.id.toUpperCase().replace('ECB-',''))}<small>${esc(row.unit)}</small></th><td>${m.name}</td><td>${m.n}</td><td>${percent(m.direction)}<small>${m.directionHits} / ${m.directionN}${ko?' · 보합 제외':' · excluding unchanged actuals'}</small></td><td>${number(m.mae)}<small>${esc(row.unit==='%'?(ko?'퍼센트포인트':'percentage points'):row.unit)}</small></td><td>${m.id==='timer-base-84m'?(ko?'제공 안 함':'Not provided'):percent(m.coverage)}</td><td>${!m.n?waiting:m.n<MIN_RANK_TARGETS?early:(ko?'실측 성과':'Observed results')}</td></tr>`)).join('');
  const rankHeaders=ko?['순위','모델','공통 평가 건수','기준 충족 지표','기준 예측 대비 오차 감소율','상태']:['Rank','Model','Paired targets','Eligible indicators','Error reduction vs baseline','Status'];
  const ranks=stats.ranking.map(m=>`<tr><td>${m.rank??'—'}</td><th scope="row">${m.name}</th><td>${m.n}</td><td>${m.eligibleIndicators} / ${m.totalIndicators}</td><td>${percent(m.skill)}</td><td>${stats.rankReady?(ko?'잠정 순위':'Provisional rank'):waiting}</td></tr>`).join('');
  const table=(caption,heads,body)=>`<div class="table-scroll" role="region" aria-label="${caption}" tabindex="0"><table class="data-table daily-performance-table"><caption class="sr-only">${caption}</caption><thead><tr>${heads.map(h=>`<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table></div>`;
  return `<section class="daily-card daily-performance" aria-labelledby="daily-performance-title"><h2 id="daily-performance-title">${title}</h2><p class="daily-hint">${ko?'미래 예측의 성공 확률은 아직 산출할 근거가 없습니다. 아래는 실제값이 발표된 과거 예측의 성과이며, 미래 성공 확률이 아닙니다. 평가 0건은 실패율 100%를 뜻하지 않습니다.':'There is not yet a basis for a calibrated future success probability. These are observed results from settled forecasts, not future success probabilities. Zero evaluated targets does not mean a 100% failure rate.'}</p>${table(title,headers,rows)}
  <h2>${ko?'모델별 예측 순위':'Model ranking'}</h2><p class="daily-hint">${ko?`모든 모델의 발행일·입력 이력·대상일이 같은 공통 예측만 비교합니다. 모든 지표에서 최소 ${MIN_RANK_TARGETS}개 대상일이 쌓이고 기준 예측 오차가 0보다 클 때 잠정 순위를 표시합니다. 현재는 지표별 기준 충족 수를 확인하세요.`:`All models must share the same issue day, input history and target for ranking. Provisional ranks require at least ${MIN_RANK_TARGETS} targets and nonzero baseline error in every indicator. Check eligible indicator counts below.`}</p>${table(ko?'모델별 예측 순위':'Model ranking',rankHeaders,ranks)}
  <details class="daily-source"><summary>${ko?'평가 기준과 해석':'Evaluation rules'}</summary><p>${ko?'최근 30일 발행 기록과 공개 실제값이 겹치는 범위에서 평가합니다. 대상 시각 전에 발행한 예측만 사용하며, 같은 모델·대상일은 최초 발행 1건만 셉니다. 갱신된 실제값에 따라 성과는 다시 계산됩니다.':'Evaluation uses the overlap of the last 30 days of issued records and published actuals. Only pre-target issues count; each model and target is scored once, using its earliest issue. Metrics are recalculated when actuals are revised.'}</p><p>${ko?'방향 적중: 입력 마지막 값 대비 상승·하락 방향이 일치한 비율입니다. 실제값 보합은 방향 평가에서 제외하며, 모델이 보합을 예측했는데 실제값이 움직이면 실패로 셉니다. 평균 절대 오차는 |대표 예측값 − 실제값|의 평균입니다. Timer는 점예측만 제공하므로 구간 포함률을 평가하지 않습니다. 구간 포함률은 실제값이 모델의 80% 예측 구간 안에 들어온 비율이며, 80% 적중을 보장하지 않습니다.':'Direction hit rate compares predicted and actual movement from the input anchor. Unchanged actuals are excluded; predicting no change when the actual moves is a miss. MAE averages absolute point estimate errors. Timer provides point forecasts only, so interval coverage is not evaluated. Coverage measures actuals inside the nominal 80% interval; 80% coverage is not guaranteed.'}</p><p>${ko?'순위 점수는 지표마다 1 − (모델 절대오차 합 ÷ 기준 예측 절대오차 합)을 구한 뒤 지표별 동일 가중 평균을 냅니다. 기준 예측은 입력 마지막 값을 그대로 유지합니다. 양수는 기준보다 오차가 작고, 음수는 큽니다. 표본 20개는 표시를 위한 최소 기준이며 통계적 우월성을 증명하지 않습니다.':'Ranking averages each indicator’s 1 − (summed model absolute error / summed baseline absolute error), with equal indicator weights. The baseline keeps the last input value unchanged. Positive scores mean lower error than baseline. Twenty targets is a display threshold, not proof of statistical superiority.'}</p></details></section>`;
}
