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

const PASS = [], FAIL = []
const check = (n, c, d = '') => { (c ? PASS : FAIL).push(n); console.log(`  ${c ? 'PASS' : 'FAIL'}  ${n}${d ? '  — ' + d : ''}`) }

const b = await chromium.launch({ headless: true, executablePath: EXE })
const ctx = await b.newContext({ viewport: { width: 1600, height: 1000 } })
const page = await ctx.newPage()
const errs = []
page.on('console', m => { if (m.type() === 'error') errs.push(m.text()) })
page.on('pageerror', e => errs.push('PAGEERROR ' + e.message))

const EMAIL = 'audit.bot@railsetu.in'
const goPolicy = async () => {
  await page.goto(BASE + '/', { waitUntil: 'networkidle', timeout: 60000 })
  // Wait for the session to settle before deciding whether to sign in, so the
  // test does not race the restore-on-load check.
  await page.waitForTimeout(900)
  if (await page.locator('.si-input').count()) {
    await page.locator('.si-input').fill(EMAIL)
    await page.locator('.si-in').click()
  }
  await page.waitForSelector('.si-name', { timeout: 20000 })
  await page.getByRole('button', { name: /^Policy$/ }).click()
  await page.waitForSelector('.card', { timeout: 20000 })
  await page.locator('.card', { hasText: 'Crowd safety thresholds' }).click()
  await page.waitForSelector('.pe-ta', { timeout: 20000 })
  await page.waitForTimeout(1200)
}

console.log('\n=== A. TAB + INITIAL STATE ===')
await goPolicy()
check('Policy tab exists and opens', await page.locator('.pol-repo').isVisible())
check('shows the document filename', (await page.locator('.pol-file').innerText()) === 'crowd-safety.yaml')
check('starts clean (matches policy in force)', (await page.locator('.pol-fmeta').innerText()).includes('matches'))
check('shows the store in use', (await page.locator('.pol-store').innerText()).length > 0,
  await page.locator('.pol-store').innerText())
check('shows a version chip', (await page.locator('.pol-vchip').innerText()).startsWith('v'))
check('editor has line numbers', (await page.locator('.pe-gutter div').count()) > 15,
  `${await page.locator('.pe-gutter div').count()} lines`)
check('Save draft disabled when unmodified', await page.locator('button:has-text("Save draft")').isDisabled())
check('Activate disabled when unmodified', await page.locator('button:has-text("Activate")').isDisabled())

console.log('\n=== B. SAVE DRAFT -> LOCALSTORAGE -> SURVIVES RELOAD ===')
const ta = page.locator('.pe-ta')
const original = await ta.inputValue()
await ta.fill(original.replace('crush_above: 5.0', 'crush_above: 4.25'))
await page.waitForTimeout(700)
check('editor marks the document modified', (await page.locator('.pol-fmeta').innerText()).includes('modified'))
check('Document tab shows a dirty dot', (await page.locator('.pol-tabs button').nth(1).innerText()).includes('●'))
check('Save draft now enabled', !(await page.locator('button:has-text("Save draft")').isDisabled()))
await page.locator('button:has-text("Save draft")').click()
await page.waitForTimeout(400)
const ls = await page.evaluate(() => localStorage.getItem('railsetu.policy.draft.crowd-safety'))
check('draft written to localStorage', !!ls && ls.includes('crush_above: 4.25'))
check('file bar confirms the draft was saved', (await page.locator('.pol-fmeta').innerText()).includes('draft saved'))
await goPolicy()
check('draft SURVIVES a full page reload',
  (await page.locator('.pe-ta').inputValue()).includes('crush_above: 4.25'))
check('still marked modified after reload', (await page.locator('.pol-fmeta').innerText()).includes('modified'))

console.log('\n=== C. VALIDATION BLOCKS ACTIVATION ===')
await page.locator('.pe-ta').fill(original.replace('crush_above: 5.0', 'crush_above: 1.5'))
await page.waitForTimeout(900)
check('invalid document shows an error state', (await page.locator('.pe-status').getAttribute('class')).includes('bad'))
check('error names the offending rule',
  (await page.locator('.pe-errs').innerText()).includes('density_bands'),
  (await page.locator('.pe-errs').innerText()).slice(0, 70))
check('Activate is DISABLED while invalid', await page.locator('button:has-text("Activate")').isDisabled())
await page.locator('.pe-ta').fill(original.replace('crush_above: 5.0', 'crush_above: 4.25'))
await page.waitForTimeout(900)
check('Activate re-enabled once valid again', !(await page.locator('button:has-text("Activate")').isDisabled()))

console.log('\n=== D. DISCARD + RESET ===')
await page.locator('button:has-text("Discard changes")').click()
await page.waitForTimeout(400)
check('discard restores the in-force document',
  (await page.locator('.pe-ta').inputValue()).includes('crush_above: 5.0'))
check('discard clears localStorage',
  (await page.evaluate(() => localStorage.getItem('railsetu.policy.draft.crowd-safety'))) === null)
await page.locator('button:has-text("Reset to shipped text")').click()
await page.waitForTimeout(500)
check('reset to defaults loads a document', (await page.locator('.pe-ta').inputValue()).length > 500)

console.log('\n=== E. PREVIEW ===')
await page.locator('.pe-ta').fill(original.replace('crush_above: 5.0', 'crush_above: 3.9')
  .replace('metered_holding_release_density: 2.5', 'metered_holding_release_density: 2.0'))
await page.waitForTimeout(800)
await page.locator('.pol-actions').getByRole('button', { name: 'Preview changes' }).click()
await page.waitForSelector('.pi-group', { timeout: 90000 })
check('preview lists the amended rules', (await page.locator('.pc-row').count()) === 2,
  `${await page.locator('.pc-row').count()} rows`)
check('preview shows before AND after columns',
  (await page.locator('.pi-cols').first().innerText()).toLowerCase().includes('in force'))
check('preview highlights moved metrics', (await page.locator('.pi-row.moved').count()) > 0,
  `${await page.locator('.pi-row.moved').count()} moved`)
check('preview renders the document diff', (await page.locator('.pd-row.add').count()) > 0)
check('diff has both add and delete rows',
  (await page.locator('.pd-row.add').count()) > 0 && (await page.locator('.pd-row.del').count()) > 0)
check('nothing activated by previewing',
  (await page.locator('.pol-vchip').innerText()) === 'v1', await page.locator('.pol-vchip').innerText())

console.log('\n=== F. PUSH MODAL VALIDATION ===')
await page.locator('.pol-actions.footer').getByRole('button', { name: /Activate…/ }).click()
await page.waitForSelector('.modal')
const submit = page.locator('.modal-actions button:has-text("Activate")')
check('modal asks for a change title', (await page.locator('.modal .fld span').first().innerText()).toLowerCase().includes('title'))
check('modal asks for a reason/description', (await page.locator('.modal textarea').count()) === 1)
check('modal shows the signed-in attribution', await page.locator('.attrib').isVisible())
check('modal does not ask for a name', (await page.locator('.fld-row').count()) === 0)
check('submit disabled with no title', await submit.isDisabled())
await page.locator('.modal .fld input').first().fill('Audit test change')
await page.waitForTimeout(250)
check('submit enabled once a title is given', !(await submit.isDisabled()))
await page.locator('.modal textarea').fill('Automated audit of the policy register.')
await submit.click()

console.log('\n=== G. HISTORY ===')
await page.waitForSelector('.gh-commit', { timeout: 120000 })
await page.waitForTimeout(800)
check('lands on the history tab after activating',
  (await page.locator('.pol-tabs button.on').innerText()).includes('Change history'))
check('two entries now (genesis + this one)', (await page.locator('.gh-commit').count()) === 2,
  `${await page.locator('.gh-commit').count()}`)
const top = page.locator('.gh-commit').first()
check('entry shows the change title', (await top.locator('.gh-ctitle').innerText()).includes('Audit test change'))
check('entry shows WHO made it', (await top.locator('.gh-cmeta b').innerText()) === 'Audit Bot')
check('entry shows their EMAIL', (await top.locator('.gh-mail').innerText()) === EMAIL)
check('entry is tagged in force', (await top.locator('.gh-tag.now').count()) === 1)
check('entry shows +/- line stats', (await top.locator('.gh-stat').innerText()).includes('+'))
check('entry shows a short hash', (await top.locator('.gh-sha').innerText()).length === 7)
check('draft cleared after activation',
  (await page.evaluate(() => localStorage.getItem('railsetu.policy.draft.crowd-safety'))) === null)
check('session persists after activating',
  (await page.evaluate(() => localStorage.getItem('railsetu.session.email'))) === EMAIL)
check('version chip advanced to v2', (await page.locator('.pol-vchip').innerText()) === 'v2')

await top.locator('.gh-crow').click()
await page.waitForSelector('.gh-cbody .pd-file', { timeout: 20000 })
check('expanding shows the description', (await top.locator('.gh-desc').innerText()).includes('Automated audit'))
check('expanding shows the rules amended', (await top.locator('.pc-row').count()) === 2,
  `${await top.locator('.pc-row').count()}`)
check('expanding shows the MEASURED effect', (await top.locator('.gh-impact-row').count()) > 0,
  `${await top.locator('.gh-impact-row').count()} rows`)
check('expanding shows a line-by-line diff', (await top.locator('.pd-row.del').count()) > 0)
check('diff rows carry old AND new line numbers', (await top.locator('.pd-ln').count()) > 4)

console.log('\n=== H. RESTORE FROM THE UI ===')
const genesis = page.locator('.gh-commit').last()
await genesis.locator('.gh-crow').click()
await page.waitForTimeout(1200)
check('the initial version offers Restore', (await genesis.locator('button:has-text("Restore this version")').count()) === 1)
check('the initial version does NOT offer Revert (it has no parent)',
  (await genesis.locator('button:has-text("Revert this change")').count()) === 0)
check('older version offers open-in-editor', (await genesis.locator('button:has-text("Open in editor")').count()) === 1)
await genesis.locator('button:has-text("Restore this version")').click()
await page.waitForSelector('.modal', { timeout: 10000 })
check('restore asks for confirmation', (await page.locator('.modal-h b').innerText()).includes('Restore'))
check('restore modal names the target version', (await page.locator('.revert-target').innerText()).includes('v1'))
check('restore modal explains later changes are undone',
  (await page.locator('.modal-sub').innerText()).includes('Anything done since is undone'))
check('restore modal shows who will be recorded',
  (await page.locator('.modal .attrib-txt b').innerText()).includes('Audit Bot'))
const t0 = Date.now()
await page.locator('.modal-actions button:has-text("Restore v")').click()
// Activation re-runs every model twice to measure the effect, so wait on the
// OUTCOME (a third entry appearing) rather than on a fixed sleep.
await page.waitForFunction(() => document.querySelectorAll('.gh-commit').length === 3,
  null, { timeout: 120000 })
console.log(`   (restore completed in ${((Date.now() - t0) / 1000).toFixed(1)}s)`)
check('restore appends a third version', (await page.locator('.gh-commit').count()) === 3,
  `${await page.locator('.gh-commit').count()}`)
check('restore is tagged as a restore', (await page.locator('.gh-tag.rs').count()) >= 1)
check('history is append-only (nothing removed)', (await page.locator('.gh-commit').count()) === 3)

console.log('\nconsole errors:', errs.length ? errs.slice(0, 6) : 'none')
check('no console errors during the whole run', errs.length === 0, errs.slice(0, 2).join(' | '))
await page.screenshot({ path: `${OUT}/audit-final.png`, fullPage: false })
console.log(`\n${'='.repeat(62)}\nFRONTEND: ${PASS.length} passed, ${FAIL.length} failed`)
if (FAIL.length) { console.log('FAILURES:'); FAIL.forEach(f => console.log('   -', f)) }
await b.close()
process.exit(FAIL.length ? 1 : 0)
