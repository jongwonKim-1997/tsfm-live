import fs from 'node:fs';
import {dashboardBoardMarkup,validLocalDashboard} from './dashboard-view.mjs';
import {escapeHTML} from './forecast-view.mjs';

/** An offline HTML report using the exact homepage chart, styles and interactions. */
export function renderDashboardDocument(data,{locale='ko',now=Date.now()}={}) {
  if(!validLocalDashboard(data,now))throw new Error('Invalid local zero-shot dashboard payload');
  const language=locale==='ko'?'ko':'en';
  const words=JSON.parse(fs.readFileSync(new URL(`../i18n/${language}.json`,import.meta.url),'utf8'));
  const css=fs.readFileSync(new URL('../styles/global.css',import.meta.url),'utf8')
    .replace(/^@import[^\n]*\n/gm,'').replace(/@theme\s*\{([^}]+)\}/g,':root {$1}');
  const script=['forecast-view.mjs','dashboard-view.mjs','dashboard-client.mjs'].map(file=>
    fs.readFileSync(new URL(file,import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'')).join('\n').replace(/<\/script/gi,'<\\/script');
  const json=JSON.stringify(words).replace(/</g,'\\u003c');
  const tirex=fs.readFileSync(new URL('../../public/licenses/tirex.txt',import.meta.url),'utf8');
  return `<!doctype html><html lang="${language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>TSFM Live · ${escapeHTML(words.forecastLocalMode)}</title><style>${css}</style></head><body><a class="skip-link" href="#main">${escapeHTML(words.skipContent)}</a><header class="site-header"><div class="header-inner"><span class="brand">TSFM <b>Live</b></span><span class="muted-text">${escapeHTML(words.forecastLocalMode)}</span></div></header><main id="main" class="page">${dashboardBoardMarkup(data,language,words,{now})}<p class="disclaimer">${escapeHTML(words.disclaimer)}</p><footer class="forecast-local-licence"><p>Built with technology from NXAI</p><details><summary>TiRex · NXAI Community License</summary><pre>${escapeHTML(tirex)}</pre></details></footer></main><script>${script}\ninitializeDashboard(document.querySelector('[data-forecast-board]'),${JSON.stringify(language)},${json});</script></body></html>`;
}
