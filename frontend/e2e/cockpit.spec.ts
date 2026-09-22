import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/** Real end-to-end walkthrough of the live docker-compose stack (Phase 7
 * DONE WHEN): log in, submit demo personas P05 then P06 through the actual
 * UI, and assert the pHash collision alert renders -- not a mock, a real
 * pipeline run against the real backend/DB. Screenshots land in
 * docs/screenshots/ for the README/deck (Phase 8/10).
 *
 * All tests in this file share ONE browser page (serial mode) and log in
 * only once per role, rather than once per test: CLAUDE.md/Phase 1 requires
 * a real login rate limit (RATE_LIMIT_LOGIN=5/minute, keyed by IP), and a
 * naive one-login-per-test suite exhausts it after 5 tests, failing the
 * 6th's login for a reason that has nothing to do with a real product bug
 * (found the hard way on the first run of this file). */
test.describe.configure({ mode: 'serial' })

import fs from 'node:fs'

const SCREENSHOT_DIR = path.resolve(__dirname, '../../docs/screenshots')

function getEnvVar(key: string): string | undefined {
  if (process.env[key]) return process.env[key]
  const envPath = path.resolve(__dirname, '../../.env')
  if (fs.existsSync(envPath)) {
    const lines = fs.readFileSync(envPath, 'utf-8').split('\n')
    for (const line of lines) {
      const trimmed = line.trim()
      if (trimmed.startsWith(`${key}=`)) {
        return trimmed.slice(key.length + 1).replace(/^["']|["']$/g, '')
      }
    }
  }
  return undefined
}

const UNDERWRITER_PASSWORD = getEnvVar('DEMO_UNDERWRITER_PASSWORD')
const AUDITOR_PASSWORD = getEnvVar('DEMO_AUDITOR_PASSWORD')

if (!UNDERWRITER_PASSWORD || !AUDITOR_PASSWORD) {
  throw new Error('DEMO_UNDERWRITER_PASSWORD and DEMO_AUDITOR_PASSWORD must be set (source them from .env)')
}

async function login(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/applications$/)
}

async function submitPersona(page: Page, personaId: string) {
  await page.goto('/applications')
  await page.getByRole('button', { name: /load demo persona/i }).click()
  await page.getByRole('button', { name: new RegExp(`^${personaId}\\b`) }).click()
  await expect(page).toHaveURL(/\/applications\/[0-9a-f-]+$/)
  // Poll until the pipeline reaches a terminal stage (COMPLETE or FAILED).
  await expect(page.getByTestId('workbench-split').or(page.getByText(/processing failed/i))).toBeVisible({
    timeout: 25_000,
  })
}

test.describe('CreditLens underwriter cockpit (live)', () => {
  let page: Page

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    // The ONE real UI login flow this suite exercises (Phase 7 DONE WHEN:
    // "log in ... through the actual UI"); every later test reuses this
    // authenticated page instead of logging in again.
    await login(page, 'underwriter@creditlens.demo', UNDERWRITER_PASSWORD!)
  })

  test.afterAll(async () => {
    await page.close()
  })

  test('P01 reaches APPROVE and shows the full decision console', async () => {
    await submitPersona(page, 'P01')
    await expect(page.getByTestId('outcome-badge').first()).toHaveAttribute('data-outcome', 'APPROVE')
    await expect(page.getByTestId('score-gauge')).toBeVisible()
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'workbench-approve.png'), fullPage: true })

    // Verify Bank Statement segment displays interactive table directly on the web with no auto-download
    await page.getByRole('tab', { name: /bank statement/i }).click()
    await expect(page.getByTestId('bank-statement-viewer').getByRole('table')).toBeVisible()
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'workbench-bank-statement.png'), fullPage: true })
  })

  test('P03 reaches DECLINE with a recourse path', async () => {
    await submitPersona(page, 'P03')
    await expect(page.getByTestId('outcome-badge').first()).toHaveAttribute('data-outcome', 'DECLINE')
    await expect(page.getByRole('heading', { name: /counterfactual recourse/i })).toBeVisible()
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'workbench-decline.png'), fullPage: true })
  })

  test('P02 reaches REFER', async () => {
    await submitPersona(page, 'P02')
    await expect(page.getByTestId('outcome-badge').first()).toHaveAttribute('data-outcome', 'REFER')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'workbench-refer.png'), fullPage: true })
  })

  test('P05 then P06 triggers the pHash syndicate collision alert', async () => {
    await submitPersona(page, 'P05')
    await submitPersona(page, 'P06')

    const alert = page.getByTestId('collision-alert')
    await expect(alert).toBeVisible()
    await expect(alert).toContainText(/document reuse detected/i)
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'collision-alert.png'), fullPage: true })

    await page.getByRole('link', { name: /open syndicate graph/i }).click()
    await expect(page).toHaveURL(/\/syndicate$/)
    await expect(page.getByRole('img', { name: /syndicate graph/i })).toBeVisible()
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'syndicate-graph.png'), fullPage: true })
  })

  test('scorecard transparency page renders the live factor config', async () => {
    await page.goto('/scorecard')
    await expect(page.getByRole('heading', { name: /how this scorecard works/i })).toBeVisible()
    await expect(page.getByText(/utility bill history/i)).toBeVisible()
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'scorecard.png'), fullPage: true })
  })

  test('application intake displays live server-side consent copy', async () => {
    await page.goto('/applications/new')
    await expect(page.getByText(/consent statement/i)).toBeVisible()
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'consent-intake.png'), fullPage: true })
  })

  test('P09 triggers prompt-injection defense and caps at REFER', async () => {
    await submitPersona(page, 'P09')
    await expect(page.getByTestId('outcome-badge').first()).toHaveAttribute('data-outcome', 'REFER')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'workbench-p09-injection.png'), fullPage: true })
  })

  test('P10 demonstrates two-signal downgrade (scorecard APPROVE -> REFER)', async () => {
    await submitPersona(page, 'P10')
    await expect(page.getByTestId('outcome-badge').first()).toHaveAttribute('data-outcome', 'REFER')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'workbench-p10-two-signal.png'), fullPage: true })
  })

  test('P11 demonstrates two-signal upgrade (scorecard DECLINE -> REFER)', async () => {
    await submitPersona(page, 'P11')
    await expect(page.getByTestId('outcome-badge').first()).toHaveAttribute('data-outcome', 'REFER')
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'workbench-p11-upgrade.png'), fullPage: true })
  })

  test('auditor can browse and verify the audit log', async () => {
    await page.evaluate(() => sessionStorage.clear())
    await login(page, 'auditor@creditlens.demo', AUDITOR_PASSWORD!)
    await page.goto('/audit')
    await expect(page.getByTestId('audit-table')).toBeVisible()
    await page.getByRole('button', { name: /verify chain/i }).click()
    await expect(page.getByRole('status')).toContainText(/verified/i, { timeout: 10_000 })
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'audit-log.png'), fullPage: true })
  })
})
