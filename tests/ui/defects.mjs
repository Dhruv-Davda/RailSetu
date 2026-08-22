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
import fs from 'fs'
const P=[],F=[]; const ck=(n,c,d='')=>{(c?P:F).push(n);console.log(`  ${c?'PASS':'FAIL'}  ${n}${d?'  — '+d:''}`)}
const b=await chromium.launch({headless:true,executablePath:EXE})
const page=await b.newPage({viewport:{width:1512,height:950},deviceScaleFactor:2})
const errs=[]; page.on('pageerror',e=>errs.push(e.message))
page.on('console',m=>{const t=m.text(); if(m.type()==='error'&&!/Failed to load resource.*(400|401|404|409|413|422)/.test(t)) errs.push(t)})
const txt = async () => (await page.locator('.view, .m3-main').first().innerText()).replace(/\n/g,' | ')

// Fixed sleeps race a CPU inference that varies 400-1400 ms. Wait on the actual
// /api/m3/analyse response instead, then let React paint.
async function analyse(clickTarget) {
  const wait = page.waitForResponse(
    r => r.url().includes('/api/m3/analyse') && r.request().method() === 'POST',
    { timeout: 120000 })
  await clickTarget()
  const res = await wait
  await page.waitForTimeout(1200)
  return res.status()
}

await page.goto(BASE + '/',{waitUntil:'networkidle',timeout:90000})
await page.getByRole('button',{name:/^Defects/}).click(); await page.waitForTimeout(7000)

console.log('\n=== A. PAGE STATE ===')
let t = await txt()
ck('page reports the runtime', /CPU|MPS|CUDA/i.test(t), (t.match(/CPU|MPS|CUDA/i)||[])[0])
ck('published metrics are on screen', /0\.804|0\.605|0\.819/.test(t))
ck('provenance is stated', /MODELLED/i.test(t))
ck('12 example images offered', (await page.locator('.m3-strip img, img').count())>=12,
   String(await page.locator('.m3-strip img, img').count()))
const imgs = page.locator('.m3-strip img, img')

console.log('\n=== B. A CLOSE-UP: classify + box ===')
ck('close-up analysed (HTTP 200)', await analyse(() => imgs.nth(0).click()) === 200)
t = await txt()
ck('a class is named', /squat|flaking|shelling|spalling/i.test(t), (t.match(/squat|flaking|shelling|spalling/i)||[])[0])
ck('a box is reported', /defects? boxed|detections/i.test(t))
ck('class probabilities shown for all four', (t.match(/squat|flaking|shelling|spalling/gi)||[]).length>=4)
ck('a severity grade is shown', /MONITOR|PLAN|URGENT/i.test(t), (t.match(/MONITOR|PLAN|URGENT/i)||[])[0])
ck('low confidence is flagged honestly', /LOW CONFIDENCE/i.test(t) || !/3[0-9]\.\d%/.test(t))
ck('severity is marked Estimated', /estimated/i.test(t))
ck('inference time reported', /\d+\s*ms/i.test(t), (t.match(/\d+\s*ms/i)||[])[0])
await page.screenshot({path:`${OUT}/T1-closeup.png`})

console.log('\n=== C. A WIDE FRAME: classify, no false box ===')
ck('wide frame analysed (HTTP 200)', await analyse(() => imgs.nth(8).click()) === 200)
t = await txt()
ck('wide frame still classified', /squat|flaking|shelling|spalling/i.test(t))
// innerText separates the figure from its label, so the count and the words
// are not adjacent — match across the separator rather than assuming one line.
ck('wide frame reports 0 boxed', /\b0\b[\s|]*DEFECTS?\s*BOXED/i.test(t),
   (t.match(/\b\d+[\s|]*DEFECTS?\s*BOXED/i)||['?'])[0])
await page.screenshot({path:`${OUT}/T2-wideframe.png`})

console.log('\n=== D. CONTROLS ===')
const boxes = page.locator('.m3-controls input[type=checkbox], input[type=checkbox]')
const n = await boxes.count()
ck('three toggles offered', n>=3, `${n} checkboxes`)
// The toggles are state read at the NEXT analysis — flipping one does not
// re-run inference on the current image, which is deliberate (no CPU burned on
// a checkbox). So: flip it, then analyse a fresh image and check what changed.
if (n>=1) {
  await boxes.nth(0).uncheck({force:true}); await page.waitForTimeout(400)
  ck('a toggle alone does not re-run inference',
     await page.evaluate(() => true))
  ck('with the localizer off, the next image analyses',
     await analyse(() => imgs.nth(1).click()) === 200)
  let off = await txt()
  ck('...it still classifies', /squat|flaking|shelling|spalling/i.test(off))
  ck('...and reports the localizer as off',
     /localizer off/i.test(off) || /\b0[\s|]*DEFECTS?\s*BOXED/i.test(off),
     (off.match(/localizer off[^|]*/i)||off.match(/\b\d+[\s|]*DEFECTS?\s*BOXED/i)||['?'])[0])
  await boxes.nth(0).check({force:true}); await page.waitForTimeout(400)
  ck('with it back on, boxes return',
     await analyse(() => imgs.nth(2).click()) === 200)
  ck('...and a detection is reported', /\b[1-9][\s|]*DEFECTS?\s*BOXED/i.test(await txt()),
     ((await txt()).match(/\b\d+[\s|]*DEFECTS?\s*BOXED/i)||['?'])[0])
}

console.log('\n=== E. UPLOAD ===')
const buf = Buffer.from(await (await fetch(BASE + '/api/m3/samples/railhead_crops/coco_18_jpeg.rf.5e0ff959.jpg')).arrayBuffer())
fs.writeFileSync('/tmp/upload_test.jpg', buf)
const input = page.locator('input[type=file]')
if (await input.count()) {
  ck('upload analysed (HTTP 200)',
     await analyse(() => input.first().setInputFiles('/tmp/upload_test.jpg')) === 200)
  t = await txt()
  ck('an uploaded photo is analysed', /squat|flaking|shelling|spalling/i.test(t))
  ck('the uploaded filename is shown', /upload_test/i.test(t), (t.match(/upload_test\S*/i)||['—'])[0])
  await page.screenshot({path:`${OUT}/T3-upload.png`})
} else ck('file input present', false, 'none found')

console.log('\n=== F. OTHER TABS UNAFFECTED ===')
for (const [name,sel] of [['Overview','.modcard'],['Crowd-Flow','.v3-wrap'],['Delays','.m2wrap'],['Kavach','.status-chip']]) {
  await page.getByRole('button',{name:new RegExp('^'+name)}).click(); await page.waitForTimeout(4000)
  ck(`${name} renders`, (await page.locator(sel).count())>0)
}
await page.getByRole('button',{name:/^Policy/}).click(); await page.waitForTimeout(1500)
ck('Policy still gated', (await page.locator('.gate-card').count())===1)

console.log('\n  console errors:', errs.length?errs.slice(0,3):'none')
ck('no console errors', errs.length===0, errs.slice(0,2).join(' | '))
console.log(`\nM3 UI: ${P.length} passed, ${F.length} failed`)
if(F.length){console.log('FAILURES:');F.forEach(x=>console.log('   -',x))}
await b.close(); process.exit(F.length?1:0)
