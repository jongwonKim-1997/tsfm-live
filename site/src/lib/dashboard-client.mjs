import {asViewed,panelMarkup,chartMarkup,highlightForecast,chooseIndicator} from './forecast-view.mjs';
import {dashboardWords,dashboardProvenance,prepareDashboard,dashboardEmptyMarkup,dashboardMarketMarkup,newerDashboardSnapshot} from './dashboard-view.mjs';

export function initializeDashboard(board,locale,baseWords) {
  if(!board)return;
  let data=JSON.parse(board.querySelector('[data-forecast-data]').textContent);
  let words=dashboardWords(baseWords,data.mode==='local_zero_shot',data.frequency==='1h');
  const panel=board.querySelector('[data-forecast-panel]');
  let selected=data.indicators.find(row=>row.id===board.dataset.selected);
  let period=board.dataset.period||'last7days',pinnedModel=null;
  const width=()=>Math.max(310,panel.clientWidth-40);
  function render(){
    const prepared=prepareDashboard(data),visible=prepared.indicators;
    selected=visible.find(row=>row.id===selected?.id)||chooseIndicator(visible);
    board.querySelector('[data-dashboard-market]').innerHTML=dashboardMarketMarkup(prepared,locale,words,selected);
    const provenance=board.querySelector('[data-dashboard-provenance]');
    if(provenance)provenance.outerHTML=dashboardProvenance(data,locale,words);
    board.querySelectorAll('[data-history-period]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.historyPeriod===period)));
    if(!selected){panel.innerHTML=dashboardEmptyMarkup(data,words);return;}
    selected=asViewed(selected);
    panel.innerHTML=panelMarkup(selected,period,locale,words,width());
    let found=false;
    panel.querySelectorAll('[data-highlight-model]').forEach(button=>{const active=button.dataset.highlightModel===pinnedModel;button.setAttribute('aria-pressed',String(active));found=found||active;});
    if(!found)pinnedModel=null;
    highlightForecast(panel,pinnedModel);
    board.querySelector('[data-forecast-announcement]').textContent=`${selected.name} · ${period==='today'?words.forecastToday:words.forecastSevenDays} · ${selected.next_session_date||words.forecastAwaiting}`;
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
  board.addEventListener('change',event=>{
    if(event.target.matches('[data-indicator-select]')){selected=data.indicators.find(row=>row.id===event.target.value);render();}
  });
  let previousWidth=0,observer=null;
  if(typeof ResizeObserver!=='undefined'){
    observer=new ResizeObserver(()=>{
      const current=width();if(Math.abs(current-previousWidth)<2||!selected)return;previousWidth=current;
      const plot=panel.querySelector('.forecast-plot');if(plot)plot.innerHTML=chartMarkup(selected,period,locale,words,current);
      highlightForecast(panel,pinnedModel);
    });observer.observe(panel);
  }
  const publicPage=board.dataset.dashboardRefresh==='public'&&['http:','https:'].includes(location.protocol);
  let refreshing=false,controller=null,timeout=null,disposed=false;
  async function refresh(){
    if(!publicPage||typeof fetch!=='function'||refreshing||disposed)return;
    refreshing=true;controller=new AbortController();timeout=setTimeout(()=>controller?.abort(),12000);
    try{
      const response=await fetch('/api/v1/local_dashboard.json',{cache:'no-store',credentials:'omit',redirect:'error',signal:controller.signal});
      if(!response.ok)throw new Error('Dashboard update unavailable');
      const candidate=await response.json();
      if(!disposed&&newerDashboardSnapshot(candidate,data)){
        data=candidate;words=dashboardWords(baseWords,data.mode==='local_zero_shot',data.frequency==='1h');
        board.querySelector('[data-forecast-data]').textContent=JSON.stringify(data);
      }
    }catch{
      // Display-time freshness still removes old observations after failed updates.
    }finally{
      clearTimeout(timeout);timeout=null;controller=null;refreshing=false;
      if(!disposed)render();
    }
  }
  render();void refresh();
  const timer=setInterval(()=>{render();void refresh();},60000);
  const onVisible=()=>{if(!document.hidden){render();void refresh();}};
  document.addEventListener('visibilitychange',onVisible);
  return ()=>{disposed=true;clearInterval(timer);clearTimeout(timeout);controller?.abort();observer?.disconnect();document.removeEventListener('visibilitychange',onVisible);};
}
