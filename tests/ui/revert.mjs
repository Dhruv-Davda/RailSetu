// Resolved at run time so the suite is portable: playwright-core comes from the
// frontend's own node_modules, the browser from the PLAYWRIGHT_CHROMIUM env var
// (or the default Playwright cache), and the target from RAILSETU_BASE.
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { existsSync, mkdirSync, readdirSync } from 'node:fs'
const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..', '..')
const { chromium } = await import(join(ROOT, 'frontend/node_modules/playwright-core/index.mjs'))
function findChromium() {
  if (process.env.PLAYWRIGHT_CHROMIUM) return process.env.PLAYWRIGHT_CHROMIUM
  const cache = join(process.env.HOME || '', 'Library/Caches/ms-playwright')
  if (!existsSync(cache)) return undefined
  for (const d of readdirSync(cache).filter((x) => x.startsWith('chromium'))) {
    for (const rel of ['chrome-mac/headless_shell',
                       'chrome-mac-arm64/headless_shell',
                       'chrome-headless-shell-mac-arm64/chrome-headless-shell',
                       'chrome-headless-shell-mac/chrome-headless-shell']) {
      const p = join(cache, d, rel)
      if (existsSync(p)) return p
    }
  }
  return undefined
}
const EXE = findChromium()
const BASE = process.env.RAILSETU_BASE || BASE
// Screenshots are test OUTPUT — keep them out of the source tree.
const OUT = process.env.RAILSETU_SHOTS || join(ROOT, 'tests', '.work', 'shots')
mkdirSync(OUT, { recursive: true })
const P=[],F=[]; const ck=(n,c,d='')=>{(c?P:F).push(n);console.log(`  ${c?'PASS':'FAIL'}  ${n}${d?'  — '+d:''}`)}
const b=await chromium.launch({headless:true,executablePath:EXE})
const ctx=await b.newContext({viewport:{width:1600,height:1050},deviceScaleFactor:2,
  permissions:['geolocation'],geolocation:{latitude:28.6428,longitude:77.2191,accuracy:20},origin:BASE})
const page=await ctx.newPage()
const errs=[]; page.on('pageerror',e=>errs.push(e.message)); // Chromium logs every non-2xx fetch as a console error. The 409 here IS the
// expected outcome and the app handles it, so only real errors are collected.
page.on('console',m=>{const t=m.text()
  if(m.type()==='error' && !/Failed to load resource.*409/.test(t)) errs.push(t)})
await page.goto(BASE + '/',{waitUntil:'networkidle'}); await page.waitForTimeout(700)
if(await page.locator('.si-input').count()){await page.locator('.si-input').fill('ops@ir.gov.in');await page.locator('.si-in').click()}
await page.waitForSelector('.si-name',{timeout:20000})
await page.getByRole('button',{name:/^Policy$/}).click()
await page.waitForSelector('.card',{timeout:20000})
await page.locator('.card',{hasText:'Crowd safety thresholds'}).click()
await page.waitForSelector('.pe-ta',{timeout:20000}); await page.waitForTimeout(700)

async function activate(from,to,title){
  await page.locator('.pol-tabs button:has-text("Document")').click(); await page.waitForTimeout(400)
  const t=await page.locator('.pe-ta').inputValue()
  await page.locator('.pe-ta').fill(t.replace(from,to)); await page.waitForTimeout(900)
  await page.locator('.pol-actions').getByRole('button',{name:'Activate…'}).click()
  await page.waitForSelector('.modal'); await page.locator('.modal .fld input').first().fill(title)
  await page.locator('.modal-actions button:has-text("Activate")').click()
  await page.waitForSelector('.gh-commit',{timeout:150000}); await page.waitForTimeout(600)
}
console.log('\n=== build v2 then v3 (two different rules) ===')
await activate('crush_above: 5.0','crush_above: 4.0','Lower crush to 4.0')
await activate('metered_holding_release_density: 2.5','metered_holding_release_density: 3.0','Raise metering to 3.0')
ck('history has 3 entries',(await page.locator('.gh-commit').count())===3)

console.log('\n=== each entry offers BOTH actions ===')
const v2row = page.locator('.gh-commit').filter({hasText:'Lower crush to 4.0'})
await v2row.locator('.gh-crow').click(); await page.waitForSelector('.gh-cbody .pd-file',{timeout:20000}); await page.waitForTimeout(400)
ck('offers "Revert this change"',(await v2row.locator('button:has-text("Revert this change")').count())===1)
ck('offers "Restore this version"',(await v2row.locator('button:has-text("Restore this version")').count())===1)
await page.screenshot({path:`${OUT}/R1-actions.png`})

console.log('\n=== git-revert v2: undo the crush change, KEEP the metering change ===')
await v2row.locator('button:has-text("Revert this change")').click()
await page.waitForSelector('.modal',{timeout:10000})
ck('dialog explains later changes are kept',(await page.locator('.modal-sub').innerText()).includes('stays in place'))
await page.screenshot({path:`${OUT}/R2-revert-dialog.png`})
await page.locator('.modal-actions button:has-text("Revert v")').click()
await page.waitForFunction(()=>document.querySelectorAll('.gh-commit').length===4,null,{timeout:150000})
await page.waitForTimeout(600)
ck('a new version is appended',(await page.locator('.gh-commit').count())===4)
ck('it is tagged as a revert',(await page.locator('.gh-tag.rb').count())>=1)
await page.locator('.pol-tabs button:has-text("Document")').click(); await page.waitForTimeout(600)
const doc=await page.locator('.pe-ta').inputValue()
ck('crush is back to 5.0', doc.includes('crush_above: 5.0'))
ck('the LATER metering change survives', doc.includes('metered_holding_release_density: 3.0'))
await page.screenshot({path:`${OUT}/R3-after-revert.png`})

console.log('\n=== conflict: revert a change a later version overwrote ===')
await activate('metered_holding_release_density: 3.0','metered_holding_release_density: 1.8','Metering to 1.8')
const v3row = page.locator('.gh-commit').filter({hasText:'Raise metering to 3.0'})
await v3row.locator('.gh-crow').click(); await page.waitForSelector('.gh-cbody .pd-file',{timeout:20000}); await page.waitForTimeout(400)
await v3row.locator('button:has-text("Revert this change")').click()
await page.waitForSelector('.modal',{timeout:10000})
await page.locator('.modal-actions button:has-text("Revert v")').click()
await page.waitForSelector('.cf',{timeout:60000}); await page.waitForTimeout(400)
const cf=(await page.locator('.modal').innerText()).replace(/\n/g,' | ')
ck('a conflict dialog is shown', cf.includes('Cannot revert'), cf.slice(0,80))
ck('it names the clashing line', /metered_holding_release_density: 3\.0/.test(cf))
ck('it says nothing was changed', /Nothing has been changed/.test(cf))
ck('it offers restore as the alternative',(await page.locator('.modal-actions button:has-text("Restore v")').count())===1)
await page.screenshot({path:`${OUT}/R4-conflict.png`})
console.log('\nconsole errors:',errs.length?errs.slice(0,3):'none')
ck('no console errors',errs.length===0)
console.log(`\n${'='.repeat(56)}\nREVERT: ${P.length} passed, ${F.length} failed`)
if(F.length){console.log('FAILURES:');F.forEach(x=>console.log('   -',x))}
await b.close(); process.exit(F.length?1:0)
