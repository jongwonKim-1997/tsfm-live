import {dailyMarkup,validDaily} from './daily-view.mjs';

export function initializeDaily(board, initial, locale='ko'){
  let data=initial,selected=data?.indicators?.[0]?.id,days=7,model='all',loading=false;
  const render=()=>{board.innerHTML=dailyMarkup(data,{locale,selected,days,model});};
  board.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
    if(b.dataset.dailyIndicator)selected=b.dataset.dailyIndicator;
    if(b.dataset.dailyDays)days=Number(b.dataset.dailyDays);
    render();
  });
  board.addEventListener('change',e=>{if(e.target.matches('[data-daily-model]')){model=e.target.value;render();}});
  async function refresh(){
    if(loading)return;loading=true;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),12000);
    try{const response=await fetch('/api/v1/daily_dashboard.json',{cache:'no-store',credentials:'omit',redirect:'error',signal:controller.signal});
      if(!response.ok)throw new Error('unavailable');const next=await response.json();
      if(validDaily(next)&&(!validDaily(data)||Date.parse(next.generated_ts_utc)>=Date.parse(data.generated_ts_utc)))data=next;
    }catch{/* Keep the dated snapshot; render always evaluates its age. */}
    finally{clearTimeout(timeout);loading=false;render();}
  }
  render();void refresh();const timer=setInterval(refresh,60000);
  return ()=>clearInterval(timer);
}
