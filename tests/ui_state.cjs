const assert = require('node:assert/strict');
const { buildSync } = require('esbuild');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
(async () => {
  const dir = mkdtempSync(join(tmpdir(), 'zepp-ui-state-'));
  try {
    const outfile = join(dir, 'utils.mjs');
    buildSync({entryPoints:['zepp_report/static/frontend-utils.js'],bundle:true,format:'esm',platform:'node',outfile});
    const {shiftRange,clampDay,createDayCache} = await import(outfile);
    assert.deepEqual(shiftRange('2024-03-01','2024-03-31',-1), ['2024-02-01','2024-02-29']);
    assert.deepEqual(shiftRange('2024-02-01','2024-02-29',1), ['2024-03-01','2024-03-31']);
    assert.deepEqual(shiftRange('2024-01-01','2024-12-31',-1), ['2023-01-01','2023-12-31']);
    assert.deepEqual(shiftRange('2026-09-03','2026-09-09',-1), ['2026-08-27','2026-09-02']);
    assert.equal(clampDay('2026-08-31','2026-09-01','2026-09-28'),'2026-09-01');
    let resolvers=[],calls=0;
    const cache=createDayCache(()=>{calls++;return new Promise(resolve=>resolvers.push(resolve))});
    const old=cache.get('day');
    assert.equal(cache.get('day'),old,'in-flight requests are shared');
    cache.clear();
    const fresh=cache.get('day');
    assert.equal(calls,2,'invalidation must not reuse old request');
    resolvers[1]({revision:'new'});await fresh;
    resolvers[0]({revision:'old'});await old;
    assert.deepEqual(await cache.get('day'),{revision:'new'},'late response cannot overwrite new cache');
    console.log('UI state: calendar periods, boundary clamp, stale cache invalidation passed');
  } finally {rmSync(dir,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exit(1)});
