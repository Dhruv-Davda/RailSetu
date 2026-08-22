// Resolved at run time so the suite is portable: playwright-core comes from the
// frontend's own node_modules, the browser from the PLAYWRIGHT_CHROMIUM env var
// (or the default Playwright cache), and the target from RAILSETU_BASE.
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { existsSync, readdirSync } from 'node:fs'
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
const OUT = process.env.RAILSETU_SHOTS || HERE
const PASS=[],FAIL=[]; const check=(n,c,d='')=>{(c?PASS:FAIL).push(n);console.log(`  ${c?'PASS':'FAIL'}  ${n}${d?'  — '+d:''}`)}
const b=await chromium.launch({headless:true,executablePath:EXE})

// --- 1. permission GRANTED, sitting at New Delhi station ---
const ctx=await b.newContext({viewport:{width:1600,height:1050},deviceScaleFactor:2,
  permissions:['geolocation'], geolocation:{latitude:28.64280,longitude:77.21910,accuracy:18},
  origin:BASE})
const page=await ctx.newPage()
const errs=[]; page.on('pageerror',e=>errs.push(e.message)); page.on('console',m=>{if(m.type()==='error')errs.push(m.text())})
const open=async(p)=>{await p.goto(BASE + '/',{waitUntil:'networkidle'})
  await p.waitForTimeout(700)
  if(await p.locator('.si-input').count()){await p.locator('.si-input').fill('asha.rao@ir.gov.in');await p.locator('.si-in').click()}
  await p.waitForSelector('.si-name',{timeout:20000})
  await p.getByRole('button',{name:/^Policy$/}).click()
  await p.waitForSelector('.card',{timeout:20000})
  await p.locator('.card',{hasText:'Crowd safety thresholds'}).click()
  await p.waitForSelector('.pe-ta',{timeout:20000}); await p.waitForTimeout(800)}

console.log('\n=== A. LOCATION GRANTED ===')
await open(page)
const t=await page.locator('.pe-ta').inputValue()
await page.locator('.pe-ta').fill(t.replace('crush_above: 5.0','crush_above: 4.4'))
await page.waitForTimeout(900)
await page.locator('.pol-actions').getByRole('button',{name:'Activate…'}).click()
await page.waitForSelector('.modal')
await page.waitForSelector('.geo.ok',{timeout:15000})
const notice=(await page.locator('.geo.ok').innerText()).replace(/\n/g,' ')
check('dialog says the change is being located', notice.includes('Recording this change at'), notice.slice(0,90))
check('it shows the coordinates', /28\.64280, 77\.21910/.test(notice))
check('it shows the accuracy', /±18 m/.test(notice))
check('it offers a map link', (await page.locator('.geo.ok a').count())===1)
await page.screenshot({path:`${OUT}/G1-granted.png`})
await page.locator('.modal .fld input').first().fill('Located change')
await page.locator('.modal-actions button:has-text("Activate")').click()
await page.waitForSelector('.gh-commit',{timeout:120000}); await page.waitForTimeout(700)
await page.locator('.gh-crow').first().click()
await page.waitForSelector('.gh-cbody .pd-file',{timeout:20000}); await page.waitForTimeout(400)
const rec=(await page.locator('.gh-impact').first().innerText()).replace(/\n/g,' | ')
check('history shows where it was made', /where this change was made/i.test(rec), rec.slice(0,120))
check('history shows the coordinates', /28\.64280, 77\.21910/.test(rec))
check('history shows the accuracy', /±18 m/.test(rec))
check('history shows the server-observed address', /address seen by the server/.test(rec))
await page.screenshot({path:`${OUT}/G2-history.png`,fullPage:false})

// --- 2. permission REFUSED ---
console.log('\n=== B. LOCATION REFUSED ===')
const ctx2=await b.newContext({viewport:{width:1600,height:1050},permissions:[]})
const p2=await ctx2.newPage()
await open(p2)
const t2=await p2.locator('.pe-ta').inputValue()
await p2.locator('.pe-ta').fill(t2.replace('crush_above: 4.4','crush_above: 4.2'))
await p2.waitForTimeout(900)
await p2.locator('.pol-actions').getByRole('button',{name:'Activate…'}).click()
await p2.waitForSelector('.modal')
await p2.waitForSelector('.geo.none',{timeout:20000})
const none=(await p2.locator('.geo.none').innerText()).replace(/\n/g,' ')
check('dialog states no location was recorded', none.includes('No location recorded'), none.slice(0,100))
check('it names the reason', /permission denied|timed out|unavailable/.test(none), none.slice(0,110))
check('it says the change still proceeds', /still made and\s+attributed|still made/.test(none))
await p2.screenshot({path:`${OUT}/G3-refused.png`})
await p2.locator('.modal .fld input').first().fill('Change without a position')
await p2.locator('.modal-actions button:has-text("Activate")').click()
await p2.waitForSelector('.gh-commit',{timeout:120000}); await p2.waitForTimeout(700)
await p2.locator('.gh-crow').first().click()
await p2.waitForSelector('.gh-cbody .pd-file',{timeout:20000}); await p2.waitForTimeout(400)
const rec2=(await p2.locator('.gh-impact').first().innerText()).replace(/\n/g,' | ')
check('history records the absence honestly', /not recorded/.test(rec2), rec2.slice(0,130))
check('no coordinates invented', !/\d+\.\d{5}, \d+\.\d{5}/.test(rec2))

console.log('\nconsole errors:', errs.length?errs.slice(0,3):'none')
check('no console errors', errs.length===0)
console.log(`\n${'='.repeat(58)}\nLOCATION: ${PASS.length} passed, ${FAIL.length} failed`)
if(FAIL.length){console.log('FAILURES:');FAIL.forEach(f=>console.log('   -',f))}
await b.close(); process.exit(FAIL.length?1:0)
