import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {violations,checkCopy,validDisclaimer,markdownCopy} from './copy-lint.mjs';
test('prohibited directional copy is rejected',()=>assert.deepEqual(violations('Our forecast is a buy signal.'),['our forecast','buy','signal']));
test('technical substrings are not product words',()=>assert.deepEqual(violations('longitude; shortfall; alphabet; model output'),[]));
test('both locales and product source are clean',()=>assert.equal(checkCopy(),true));
test('only the exact reviewed disclaimer is exempt',()=>{
  for(const locale of ['en','ko']){
    const text=JSON.parse(fs.readFileSync(`src/i18n/${locale}.json`,'utf8')).disclaimer;
    assert.equal(validDisclaimer(locale,text),true);
    assert.equal(validDisclaimer(locale,text+' Our forecast is a buy signal.'),false);
    assert.equal(validDisclaimer(locale,text.replace('TSFM Live','A different operator')),false);
    assert.equal(validDisclaimer(locale,''),false);
  }
});
test('disclaimer key cannot hide injected promotional text',()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'tsfm-copy-'));
  try{
    fs.mkdirSync(path.join(dir,'i18n'));
    for(const locale of ['en','ko']){
      const strings=JSON.parse(fs.readFileSync(`src/i18n/${locale}.json`,'utf8'));
      strings.disclaimer+=' Our forecast is a buy signal.';
      fs.writeFileSync(path.join(dir,`i18n/${locale}.json`),JSON.stringify(strings));
    }
    assert.throws(()=>checkCopy(dir),/exact reviewed text required/);
  }finally{
    const target=fs.realpathSync(dir),parent=fs.realpathSync(os.tmpdir());
    assert.ok(target.startsWith(parent+path.sep),'temporary cleanup stays under the temp directory');
    fs.rmSync(target,{recursive:true,force:true});
  }
});
test('methodology checks visible labels and examples without flagging URL paths',()=>{
  assert.deepEqual(violations(markdownCopy('[Reference](https://example.org/short)')),[]);
  assert.deepEqual(violations(markdownCopy('[Our forecast](https://example.org/reference)')),['our forecast']);
  assert.deepEqual(violations(markdownCopy('`buy signal`')),['buy','signal']);
});
