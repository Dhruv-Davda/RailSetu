/*
 * The 3D layer: both scenes, every camera, in a real browser.
 *
 * What is worth asserting about a 3D view is not what it looks like — that is a
 * screenshot's job — but that it is DRIVEN BY THE SAME DATA as everything else
 * and that switching cameras does not break it. So: the canvas exists and has
 * drawn something; the scene's own caption states what is real and what is
 * schematic; every camera renders; the toggles round-trip; and no WebGL or React
 * error reaches the console at any point.
 *
 * Requires the dev server and the API. Run via tests/run.sh, or:
 *   RAILSETU_BASE=http://localhost:5173 node tests/ui/three.mjs
 */
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
    for (const rel of ['chrome-mac/headless_shell', 'chrome-mac-arm64/headless_shell',
                       'chrome-headless-shell-mac-arm64/chrome-headless-shell',
                       'chrome-headless-shell-mac/chrome-headless-shell']) {
      const p = join(cache, d, rel)
      if (existsSync(p)) return p
    }
  }
  return undefined
}

const BASE = process.env.RAILSETU_BASE || 'http://localhost:5173'
const P = [], F = []
const ck = (n, c, d = '') => {
  ;(c ? P : F).push(n)
  console.log(`  ${c ? 'PASS' : 'FAIL'}  ${n}${d ? '  — ' + String(d).slice(0, 110) : ''}`)
}

const browser = await chromium.launch({
  headless: true,
  executablePath: findChromium(),
  // SwiftShader so the scenes actually rasterise on a headless box with no GPU.
  args: ['--use-gl=angle', '--enable-unsafe-swiftshader'],
})
const page = await browser.newPage({ viewport: { width: 1500, height: 900 } })

const errors = []
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
page.on('console', (m) => {
  const t = m.text()
  if (m.type() === 'error' && !/Failed to load resource.*(40[0-9]|500)/.test(t)) {
    errors.push('console: ' + t)
  }
})

const btn = (name) => page.getByRole('button', { name: new RegExp(`^${name}$`, 'i') }).first()
const tab = async (name) => {
  await page.getByRole('button', { name: new RegExp('^' + name) }).first().click()
  await page.waitForTimeout(3500)
}

/*
 * Whether the scene actually DREW something.
 *
 * readPixels() is no good here: react-three-fiber leaves preserveDrawingBuffer
 * off, so the buffer is already cleared by the time a test could read it, and
 * every scene would look blank. Playwright's screenshot captures the COMPOSITED
 * page, which does include the WebGL output — so encode the canvas region and
 * look at how well it compresses. A flat fill of one colour packs down to a few
 * KB; geometry, colour and text do not.
 */
async function canvasDrew() {
  const el = page.locator('canvas').first()
  if (!(await el.count())) return { ok: false, why: 'no canvas' }
  const box = await el.boundingBox()
  if (!box || box.width < 50 || box.height < 50) return { ok: false, why: 'canvas has no size', box }
  const png = await page.screenshot({ clip: box })
  return { ok: png.length > 8000, kb: Math.round(png.length / 1024), size: [box.width, box.height] }
}

await page.goto(BASE + '/', { waitUntil: 'networkidle', timeout: 90000 })
await page.waitForTimeout(2500)

// ───────────────────────────────────────────────── the station scene
console.log('\n=== 1. THE STATION IN 3D ===')
await tab('Crowd-Flow')
await page.waitForTimeout(4000)
ck('the view opens in 3D by default', await btn('3D').evaluate((e) => e.className.includes('on')))
await page.waitForTimeout(7000)

ck('a canvas is mounted', (await page.locator('canvas').count()) > 0)
let drew = await canvasDrew()
ck('the scene has rasterised something', drew.ok, JSON.stringify(drew))

const cap = await page.locator('.v3-note, [class*="note"]').first().innerText().catch(() => '')
ck('the scene captions itself', cap.length > 40, cap.slice(0, 80))
ck('it says which parts are real', /real/i.test(cap), cap.slice(0, 110))
ck('it says which parts are schematic', /schematic/i.test(cap), cap.slice(0, 110))
ck('it names OpenStreetMap as the source of the alignments', /openstreetmap/i.test(cap))
ck('it does not claim to track individual passengers',
   /aggregate/i.test(cap) && /not individual/i.test(cap), cap.slice(0, 140))

console.log('\n=== 2. EVERY STATION CAMERA RENDERS ===')
for (const view of ['Aerial', 'FOB crush', 'Platform', 'Deck']) {
  await btn(view).click()
  await page.waitForTimeout(6000)
  const d = await canvasDrew()
  ck(`${view}: renders`, d.ok, JSON.stringify(d))
  ck(`${view}: is the selected camera`,
     await btn(view).evaluate((e) => e.className.includes('on')))
}
ck('no error from switching cameras', errors.length === 0, errors.join(' | '))

console.log('\n=== 3. THE SCENE FOLLOWS THE SIMULATION ===')
await btn('Aerial').click()
await page.waitForTimeout(4000)
const before = await page.locator('.m3-metric, .metric, header').first().innerText().catch(() => '')
// Applying a mitigation re-runs the model; the scene must re-render from it.
const metered = page.locator('label').filter({ hasText: 'Metered holding' }).first()
await metered.click()
await page.waitForTimeout(9000)
const after = await page.locator('.view, .m1-main, body').first().innerText()
ck('applying a measure changes the headline the scene is drawn from',
   /3\.\d|MANAGED/i.test(after), after.slice(0, 90).replace(/\n/g, ' | '))
ck('the scene still renders afterwards', (await canvasDrew()).ok)
await metered.click()
await page.waitForTimeout(6000)
ck('turning it off again restores the critical state',
   /CRITICAL|17\./i.test(await page.locator('.view, .m1-main, body').first().innerText()))

console.log('\n=== 4. 2D AND 3D ARE TWO VIEWS OF ONE RESULT ===')
await btn('2D MAP').click()
await page.waitForTimeout(5000)
ck('2D shows a Leaflet map', (await page.locator('.leaflet-container').count()) > 0)
ck('the 3D canvas is gone', (await page.locator('canvas').count()) === 0)
const twoD = await page.locator('.view, .m1-main, body').first().innerText()
await btn('3D').click()
await page.waitForTimeout(8000)
const threeD = await page.locator('.view, .m1-main, body').first().innerText()
const num = (t) => (t.match(/1?\d\.\d\d?\s*p\/m/) || [''])[0]
ck('both views report the same peak density', num(twoD) === num(threeD), [num(twoD), num(threeD)])
ck('the canvas comes back', (await canvasDrew()).ok)

// ───────────────────────────────────────────────── the corridor scene
console.log('\n=== 5. THE CORRIDOR IN 3D ===')
await tab('Delays')
await page.waitForTimeout(6000)
ck('the corridor opens in 3D', await btn('3D').evaluate((e) => e.className.includes('on')))
await page.waitForTimeout(6000)
drew = await canvasDrew()
ck('the corridor scene rasterises', drew.ok, JSON.stringify(drew))

const ccap = await page.locator('.v3-note, [class*="note"]').first().innerText().catch(() => '')
ck('it captions its own scale', /1 unit = 1 km/i.test(ccap), ccap.slice(0, 90))
ck('it says the sizes are exaggerated', /exaggerat/i.test(ccap), ccap.slice(0, 110))
ck('it says the trains come from the simulated timeline',
   /simulated timeline/i.test(ccap), ccap.slice(0, 130))
ck('it explains what the loop line means', /loop line/i.test(ccap), ccap.slice(0, 150))

console.log('\n=== 6. EVERY CORRIDOR CAMERA RENDERS ===')
for (const view of ['Corridor', 'Platform \\(trains pass\\)', 'Chase train', 'Overhead']) {
  await page.getByRole('button', { name: new RegExp('^' + view + '$', 'i') }).first().click()
  await page.waitForTimeout(7000)
  ck(`${view.replace('\\', '')}: renders`, (await canvasDrew()).ok)
}

console.log('\n=== 7. PLAYBACK AND FOCUS ===')
await btn('Corridor').click()
await page.waitForTimeout(4000)
const clockText = () => page.locator('.v3-clock').first().innerText()
const t0 = await clockText()
await page.waitForTimeout(4000)
const t1 = await clockText()
ck('the simulated clock advances during playback', t0 !== t1, [t0, t1])
const chips = page.locator('.v3-chip')
ck('every train has a chip to focus on', (await chips.count()) >= 5, await chips.count())
await chips.first().click()
await page.waitForTimeout(8000)
ck('focusing a train selects it', await chips.first().evaluate((e) => e.className.includes('on')))
ck('...and switches to the chase camera',
   await btn('Chase train').evaluate((e) => e.className.includes('on')))
ck('the scene still renders while chasing', (await canvasDrew()).ok)
await chips.first().click()
await page.waitForTimeout(3000)
ck('unfocusing releases the train', !(await chips.first().evaluate((e) => e.className.includes('on'))))

console.log('\n=== 8. THE OPTIMIZER TOGGLE REACHES THE SCENE ===')
const resched = page.getByRole('button', { name: /Run rescheduling optimizer/i }).first()
if (await resched.count()) {
  await resched.click()
  await page.waitForTimeout(9000)
  const body = await page.locator('.view, body').first().innerText()
  ck('rescheduling changes the corridor headline', /RESCHEDULED/i.test(body))
  ck('the scene says held trains sit on the loop', /loop line/i.test(body))
  ck('the scene still renders after morphing', (await canvasDrew()).ok)
  const revert = page.getByRole('button', { name: /Revert to no-action/i }).first()
  if (await revert.count()) {
    await revert.click()
    await page.waitForTimeout(7000)
    ck('reverting returns to the cascade',
       /NO ACTION/i.test(await page.locator('.view, body').first().innerText()))
    ck('...and the scene survives that too', (await canvasDrew()).ok)
  }
}

console.log('\n=== 9. NOTHING BROKE ===')
ck('no uncaught page error in any scene or camera', errors.length === 0, errors.join(' | '))

await browser.close()
console.log(`\n${'='.repeat(62)}\n3D SCENES: ${P.length}/${P.length + F.length} passed, ${F.length} failed`)
F.forEach((f) => console.log('   -', f))
process.exit(F.length ? 1 : 0)
