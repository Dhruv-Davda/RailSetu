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
const P=[],F=[]; const ck=(n,c,d='')=>{(c?P:F).push(n);console.log(`  ${c?'PASS':'FAIL'}  ${n}${d?'  — '+d:''}`)}
const b=await chromium.launch({headless:true,executablePath:EXE})
const ctx=await b.newContext({viewport:{width:1512,height:1000},deviceScaleFactor:2,
  permissions:['geolocation'],geolocation:{latitude:28.6428,longitude:77.2191,accuracy:15},origin:BASE})
const page=await ctx.newPage()
const errs=[]; page.on('pageerror',e=>errs.push(e.message))
page.on('console',m=>{const t=m.text(); if(m.type()==='error' && !/Failed to load resource.*(409|400)/.test(t)) errs.push(t)})
await page.goto(BASE + '/',{waitUntil:'networkidle'}); await page.waitForTimeout(700)
await page.locator('.si-input').fill('ops@ir.gov.in'); await page.locator('.si-in').click()
await page.waitForSelector('.si-name',{timeout:20000})
await page.getByRole('button',{name:/^Policy$/}).click()
await page.waitForSelector('.card',{timeout:20000}); await page.waitForTimeout(600)
const before=await page.locator('.card').count()
ck('library starts with 8 documents', before===8, String(before))

console.log('\n=== the three steps ===')
await page.locator('.lib-new').click()
await page.waitForSelector('.modal.wide',{timeout:10000})
const steps=await page.locator('.step').allInnerTexts()
const flat = steps.join(' | ').replace(/\n/g,'').toLowerCase()
ck('modal walks file type -> name -> body',
   /1\s*file type/.test(flat) && /2\s*name/.test(flat) && /3\s*body/.test(flat),
   steps.join(' / ').replace(/\n/g,''))
ck('two file types offered',(await page.locator('.type').count())===2)
ck('markdown selected by default',(await page.locator('.type.on .type-name').innerText())==='Markdown')
ck('explains why rule-sets cannot be added',
  (await page.locator('.modal-note').first().innerText()).includes('nothing reading it'))
ck('Add is disabled with no title', await page.locator('.modal-actions button:has-text("Add policy")').isDisabled())
await page.screenshot({path:`${OUT}/N1-new.png`})

console.log('\n=== fill it in ===')
await page.locator('.modal .fld input').first().fill('Platform announcement standards')
await page.waitForTimeout(300)
ck('shows the filename it will use',(await page.locator('.slug').innerText()).includes('platform-announcement-standards.md'),
   (await page.locator('.slug').innerText()))
ck('body is pre-seeded with a starter',(await page.locator('.newbody').inputValue()).includes('Platform announcement standards'))
await page.locator('.type').nth(1).click(); await page.waitForTimeout(300)
ck('switching to plain text updates the extension',(await page.locator('.slug').innerText()).includes('.txt'))
ck('...and reseeds the starter',(await page.locator('.newbody').inputValue()).includes('PLATFORM ANNOUNCEMENT STANDARDS'))
await page.locator('.type').first().click(); await page.waitForTimeout(300)
const ins=await page.locator('.modal .fld input').all()
await ins[1].fill('What is announced, in what order and in which languages.')
await ins[2].fill('Station Operations & Safety')
const labels = (await page.locator('.modal .fld > span').allInnerTexts()).join(' | ')
ck('the field is labelled Department, not Owner',
   /department/i.test(labels) && !/owner/i.test(labels), labels.replace(/\n/g,' '))
await page.locator('.newbody').fill('# Platform Announcement Standards\n\nSafety instruction first, always.\n\n1. Hindi\n2. English\n3. Regional language\n')
await page.waitForTimeout(300)
ck('location is captured for the new document', await page.locator('.geo.ok').isVisible())
await page.screenshot({path:`${OUT}/N2-filled.png`})
await page.locator('.modal-actions button:has-text("Add policy")').click()

console.log('\n=== it lands, and opens ===')
await page.waitForSelector('.pe-ta',{timeout:60000}); await page.waitForTimeout(700)
ck('the author lands in the new document',(await page.locator('.pol-file').innerText())==='platform-announcement-standards.md',
   await page.locator('.pol-file').innerText())
ck('it starts at v1',(await page.locator('.pol-vchip').innerText())==='v1')
ck('it is a written standard (no modelled effect)',
  (await page.locator('.pol-hint').innerText()).includes('no modelled effect'))
await page.locator('.pol-tabs button:has-text("Policies")').click()
await page.waitForSelector('.card',{timeout:20000}); await page.waitForTimeout(500)
ck('the library now has 9', (await page.locator('.card').count())===9, String(await page.locator('.card').count()))
ck('it sits under Written standards',
  (await page.locator('.lib-group').last().innerText()).includes('Platform announcement standards'))
await page.screenshot({path:`${OUT}/N3-library.png`})

console.log('\n=== duplicate is refused ===')
await page.locator('.lib-new').click(); await page.waitForSelector('.modal.wide')
await page.locator('.modal .fld input').first().fill('Platform announcement standards')
await page.waitForTimeout(300)
await page.locator('.modal-actions button:has-text("Add policy")').click()
await page.waitForSelector('.error-chip',{timeout:20000})
ck('the error reads as a sentence, not a transport code',
  !/API \d+ on/.test(await page.locator('.error-chip').innerText()),
  await page.locator('.error-chip').innerText())
ck('a duplicate title is rejected with a reason',
  (await page.locator('.error-chip').innerText()).includes('already exists'),
  await page.locator('.error-chip').innerText())
console.log('\nconsole errors:', errs.length?errs.slice(0,3):'none')
ck('no console errors', errs.length===0)
console.log(`\n${'='.repeat(56)}\nADD POLICY: ${P.length} passed, ${F.length} failed`)
if(F.length){console.log('FAILURES:');F.forEach(x=>console.log('   -',x))}
await b.close(); process.exit(F.length?1:0)
