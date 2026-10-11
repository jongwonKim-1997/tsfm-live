import fs from 'node:fs';
import path from 'node:path';
import {parseArgs} from 'node:util';
import {randomUUID} from 'node:crypto';
import {renderDashboardDocument} from '../src/lib/local-dashboard.mjs';

const {values}=parseArgs({options:{input:{type:'string'},output:{type:'string'},locale:{type:'string',default:'ko'}}});
if(!values.input||!values.output)throw new Error('Usage: node scripts/render-local-dashboard.mjs --input dashboard.json --output dashboard.html [--locale ko|en]');
const data=JSON.parse(fs.readFileSync(values.input,'utf8'));
const html=renderDashboardDocument(data,{locale:values.locale});
fs.mkdirSync(path.dirname(path.resolve(values.output)),{recursive:true});
const temporary=path.resolve(values.output)+'.'+randomUUID()+'.tmp';
try {
  fs.writeFileSync(temporary,html,'utf8');
  fs.renameSync(temporary,values.output);
} finally {
  if(fs.existsSync(temporary))fs.unlinkSync(temporary);
}
console.log(`Local dashboard rendered: ${path.resolve(values.output)}`);
