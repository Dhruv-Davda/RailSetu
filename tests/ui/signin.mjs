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
const PASS = [], FAIL = []
const check = (n, c, d = '') => { (c ? PASS : FAIL).push(n); console.log(`  ${c ? 'PASS' : 'FAIL'}  ${n}${d ? '  — ' + d : ''}`) }

const b = await chromium.launch({ headless: true, executablePath: EXE })
const page = await b.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 })
const errs = []
page.on('console', m => { if (m.type() === 'error') errs.push(m.text()) })
page.on('pageerror', e => errs.push('PAGEERROR ' + e.message))
const go = async () => { await page.goto(BASE + '/', { waitUntil: 'networkidle', timeout: 60000 }); await page.waitForTimeout(600) }

console.log('\n=== A. SIGNED OUT ===')
await go()
check('sign-in box in the top bar', await page.locator('.si-input').isVisible())
check('Sign in button present', await page.locator('.si-in').isVisible())
check('no sign-out button while signed out', (await page.locator('.si-out').count()) === 0)
check('Sign in disabled on an empty field', await page.locator('.si-in').isDisabled())
await page.locator('.si-input').fill('not-an-email')
check('Sign in disabled on a malformed address', await page.locator('.si-in').isDisabled())
await page.screenshot({ path: `${OUT}/a1-signedout.png` })

console.log('\n=== B. POLICY TAB IS GATED ===')
await page.getByRole('button', { name: /^Policy$/ }).click()
await page.waitForSelector('.gate', { timeout: 10000 })
check('policy tab shows a sign-in prompt', await page.locator('.gate-card h2').isVisible())
check('prompt explains why', (await page.locator('.gate-card p').first().innerText()).toLowerCase().includes('who you are'))
check('the editor is NOT rendered', (await page.locator('.pe-ta').count()) === 0)
check('the change history is NOT rendered', (await page.locator('.gh-commit').count()) === 0)
check('the policy library is NOT rendered', (await page.locator('.card').count()) === 0)
check('gate offers its own sign-in field', await page.locator('.gate-form input').isVisible())
await page.screenshot({ path: `${OUT}/a2-gate.png` })
check('other tabs still work signed out', await (async () => {
  await page.getByRole('button', { name: /Kavach/ }).click()
  await page.waitForTimeout(1500)
  return (await page.locator('.status-chip').count()) > 0
})())

console.log('\n=== C. SIGN IN FROM THE GATE ===')
await page.getByRole('button', { name: /^Policy$/ }).click()
await page.waitForSelector('.gate-form input')
await page.locator('.gate-form input').fill('Asha.Rao@ir.gov.in')
await page.locator('.gate-form button').click()
await page.waitForSelector('.card', { timeout: 30000 })
check('signing in opens the policy library', (await page.locator('.card').count()) === 8,
  `${await page.locator('.card').count()} documents`)
check('only the Policies tab is shown before opening one',
  (await page.locator('.pol-tabs button').count()) === 1,
  (await page.locator('.pol-tabs button').allInnerTexts()).join(' | '))
await page.locator('.card', { hasText: 'Crowd safety thresholds' }).click()
await page.waitForSelector('.pe-ta', { timeout: 20000 })
check('opening a document reveals the rest of the tabs',
  (await page.locator('.pol-tabs button').count()) === 4,
  (await page.locator('.pol-tabs button').allInnerTexts()).join(' | '))
check('the document opens in the editor', await page.locator('.pe-ta').isVisible())
check('top bar now shows the person', (await page.locator('.si-name').innerText()) === 'Asha Rao')
check('top bar shows their address (normalised)', (await page.locator('.si-mail').innerText()) === 'asha.rao@ir.gov.in')
check('avatar shows initials', (await page.locator('.si-av').innerText()) === 'AR')
check('sign-out button appears', await page.locator('.si-out').isVisible())
check('the email field is gone', (await page.locator('.si-input').count()) === 0)
await page.screenshot({ path: `${OUT}/a3-signedin.png` })

console.log('\n=== D. SESSION SURVIVES RELOAD ===')
await go()
check('still signed in after a reload', (await page.locator('.si-name').innerText()) === 'Asha Rao')
await page.getByRole('button', { name: /^Policy$/ }).click()
await page.waitForSelector('.card', { timeout: 20000 })
await page.locator('.card', { hasText: 'Crowd safety thresholds' }).click()
await page.waitForSelector('.pe-ta', { timeout: 20000 })
check('policy still open after a reload', await page.locator('.pe-ta').isVisible())

console.log('\n=== E. IDENTITY DRIVES ATTRIBUTION ===')
const ta = page.locator('.pe-ta')
const doc = await ta.inputValue()
await ta.fill(doc.replace('crush_above: 5.0', 'crush_above: 4.1'))
await page.waitForTimeout(900)
await page.locator('.pol-actions').getByRole('button', { name: 'Activate…' }).click()
await page.waitForSelector('.modal')
check('push modal does NOT ask for a name', (await page.locator('.modal .fld-row').count()) === 0)
check('push modal shows who it will be recorded as', await page.locator('.attrib').isVisible())
check('attribution names the signed-in person',
  (await page.locator('.attrib-txt b').innerText()).includes('Asha Rao'))
check('attribution shows their address',
  (await page.locator('.attrib-txt span').innerText()).includes('asha.rao@ir.gov.in'))
await page.screenshot({ path: `${OUT}/a4-push.png` })
await page.locator('.modal .fld input').first().fill('Tighten crush threshold')
await page.locator('.modal textarea').fill('Signed-in attribution check.')
await page.locator('.modal-actions button:has-text("Activate")').click()
await page.waitForSelector('.gh-commit', { timeout: 120000 })
await page.waitForTimeout(700)
const top = page.locator('.gh-commit').first()
check('history records the signed-in name', (await top.locator('.gh-cmeta b').innerText()) === 'Asha Rao')
check('history records the signed-in address', (await top.locator('.gh-mail').innerText()) === 'asha.rao@ir.gov.in')
await page.screenshot({ path: `${OUT}/a5-history.png`, fullPage: false })

console.log('\n=== F. A SECOND PERSON ===')
await page.locator('.si-out').click()
await page.waitForTimeout(1200)
check('sign-out returns the email box', await page.locator('.si-input').isVisible())
check('sign-out clears the box', (await page.locator('.si-input').inputValue()) === '')
check('sign-out leaves the policy tab', (await page.locator('.pe-ta').count()) === 0)
check('local session cleared',
  (await page.evaluate(() => localStorage.getItem('railsetu.session.email'))) === null)
await page.locator('.si-input').fill('d.k.verma@rdso.in')
await page.locator('.si-in').click()
await page.waitForTimeout(2500)
check('second person signed in', (await page.locator('.si-name').innerText()) === 'D K Verma')
await page.getByRole('button', { name: /^Policy$/ }).click()
await page.waitForSelector('.card', { timeout: 20000 })
await page.locator('.card', { hasText: 'Crowd safety thresholds' }).click()
await page.waitForSelector('.pe-ta', { timeout: 20000 })
const doc2 = await page.locator('.pe-ta').inputValue()
await page.locator('.pe-ta').fill(doc2.replace('one_way_fob_egress_multiplier: 2.5', 'one_way_fob_egress_multiplier: 2.2'))
await page.waitForTimeout(900)
await page.locator('.pol-actions').getByRole('button', { name: 'Activate…' }).click()
await page.waitForSelector('.modal')
await page.locator('.modal .fld input').first().fill('FOB egress review')
await page.locator('.modal-actions button:has-text("Activate")').click()
await page.waitForSelector('.gh-commit', { timeout: 120000 })
await page.waitForTimeout(700)
const rows = await page.locator('.gh-commit').all()
const authors = []
for (const r of rows) authors.push((await r.locator('.gh-mail').innerText()))
console.log('   history authors:', authors)
check('history shows two different people', new Set(authors).size >= 2, authors.join(', '))
check('newest change is by the second person', authors[0] === 'd.k.verma@rdso.in')
check('earlier change still attributed to the first', authors.includes('asha.rao@ir.gov.in'))
await page.screenshot({ path: `${OUT}/a6-two-users.png`, fullPage: false })

console.log('\nconsole errors:', errs.length ? errs.slice(0, 5) : 'none')
check('no console errors', errs.length === 0, errs.slice(0, 2).join(' | '))
console.log(`\n${'='.repeat(60)}\nAUTH: ${PASS.length} passed, ${FAIL.length} failed`)
if (FAIL.length) { console.log('FAILURES:'); FAIL.forEach(f => console.log('   -', f)) }
await b.close()
process.exit(FAIL.length ? 1 : 0)
