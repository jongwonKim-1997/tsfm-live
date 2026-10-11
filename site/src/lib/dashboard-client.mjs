import {asViewed,panelMarkup,chartMarkup,highlightForecast} from './forecast-view.mjs';
import {dashboardWords,dashboardProvenance} from './dashboard-view.mjs';

export function initializeDashboard(board,locale,baseWords) {
  if(!board)return;
  const data=JSON.parse(board.querySelector('[data-forecast-data]').textContent);
  const words=dashboardWords(baseWords,data.mode==='local_zero_shot');
  const panel=board.querySelector('[data-forecast-panel]');
  let selected=data.indicators.find(row=>row.id===board.dataset.selected);
  let period=board.dataset.period||'last7days', pinnedModel=null;
  const width=()=>Math.max(310,panel.clientWidth-40);
  function render(){
    if(!selected)return;
    selected=asViewed(selected);
    panel.innerHTML=panelMarkup(selected,period,locale,words,width());
    let found=false;
    panel.querySelectorAll('[data-highlight-model]').forEach(button=>{const active=button.dataset.highlightModel===pinnedModel;button.setAttribute('aria-pressed',String(active));found=found||active;});
    if(!found)pinnedModel=null;
    highlightForecast(panel,pinnedModel);
    board.querySelectorAll('[data-indicator]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.indicator===selected.id)));
    board.querySelector('[data-indicator-select]').value=selected.id;
    board.querySelectorAll('[data-history-period]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.historyPeriod===period)));
    board.querySelector('[data-forecast-announcement]').textContent=`${selected.name} · ${period==='today'?words.forecastToday:words.forecastSevenDays} · ${selected.next_session_date||words.forecastAwaiting}`;
    const provenance=board.querySelector('[data-dashboard-provenance]');
    if(provenance)provenance.outerHTML=dashboardProvenance(data,locale,words);
  }
  board.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button)return;
    if(button.dataset.indicator){selected=data.indicators.find(row=>row.id===button.dataset.indicator);render();}
    if(button.dataset.historyPeriod){period=button.dataset.historyPeriod;render();}
    if(button.dataset.highlightModel){
      const active=button.getAttribute('aria-pressed')!=='true',id=button.dataset.highlightModel;
      pinnedModel=active?id:null;
      panel.querySelectorAll('[data-highlight-model]').forEach(row=>row.setAttribute('aria-pressed',String(active&&row.dataset.highlightModel===id)));
      highlightForecast(panel,pinnedModel);
    }
  });
  for(const eventName of ['pointerover','focusin'])panel.addEventListener(eventName,event=>{
    const button=event.target.closest('[data-highlight-model]');if(button)highlightForecast(panel,button.dataset.highlightModel);
  });
  for(const eventName of ['pointerout','focusout'])panel.addEventListener(eventName,event=>{
    const button=event.relatedTarget?.closest?.('[data-highlight-model]');highlightForecast(panel,button?.dataset.highlightModel||pinnedModel);
  });
  board.querySelector('[data-indicator-select]')?.addEventListener('change',event=>{selected=data.indicators.find(row=>row.id===event.target.value);render();});
  let previousWidth=0;
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>{
    const current=width();if(Math.abs(current-previousWidth)<2||!selected)return;previousWidth=current;
    const plot=panel.querySelector('.forecast-plot');if(plot)plot.innerHTML=chartMarkup(selected,period,locale,words,current);
    highlightForecast(panel,pinnedModel);
  }).observe(panel);
  render();
  const timer=setInterval(render,60000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)render();});
  return ()=>clearInterval(timer);
}
