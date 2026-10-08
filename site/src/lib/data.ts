import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import en from '../i18n/en.json';
import ko from '../i18n/ko.json';

const base = path.resolve(process.env.TSFM_API_DIR || 'public/api/v1');
export const read = (name: string) => JSON.parse(fs.readFileSync(path.join(base, name + '.json'), 'utf8'));
export const meta = read('meta');
export function language(locale: string) {
  const words: Record<string, string> = locale === 'ko' ? ko : en;
  return (key: string) => words[key] || key;
}
export function number(value: unknown, locale = 'en', digits = 1) {
  return value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' :
    new Intl.NumberFormat(locale === 'ko' ? 'ko-KR' : 'en-US', {maximumFractionDigits: digits}).format(Number(value));
}
export const percent = (v: any, locale = 'en') => v == null ? '—' : `${number(v * 100, locale)}%`;
export const href = (locale: string, route: string) => (locale === 'ko' ? '/ko' : '') + (route === '/' && locale === 'ko' ? '/' : route);
export function routes() {
  const paths = ['', 'models', 'indicators', 'today', 'ledger', 'methodology', 'status', 'about', 'api'];
  paths.push(...meta.entrants.map((m: any) => 'models/' + m.id), ...meta.indicators.map((i: any) => 'indicators/' + i.id));
  const folder = path.join(base, 'scorecards');
  if (fs.existsSync(folder)) paths.push(...fs.readdirSync(folder).filter(x => x.endsWith('.json')).map(x => 'scorecard/' + x.slice(0,-5)));
  return ['en','ko'].flatMap(locale => paths.map(route => ({
    params: {path: [locale === 'ko' ? 'ko' : '', route].filter(Boolean).join('/') || undefined},
    props: {locale, route}
  })));
}

const changedAt=(file:string)=>Number(spawnSync('git',['-C','..','log','-1','--format=%ct','--',file],{encoding:'utf8'}).stdout?.trim()||0);
export const translationStale=changedAt('docs/methodology.ko.md')<changedAt('docs/methodology.md');
