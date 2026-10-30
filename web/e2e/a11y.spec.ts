// Barrierefreiheit (axe-core, die Engine hinter Lighthouse-a11y): keine kritischen/ernsten Verstöße auf allen Seiten, hell + dunkel.
import AxeBuilder from '@axe-core/playwright'
import { expect, settled, test } from './fixtures'

const PATHS = ['cockpit', 'empfehlung', 'was-waere-wenn', 'splitter', 'sensitivitaet', 'risiko', 'pareto', 'erloes-stapel', 'plasma', 'cdr', 'eeg',
  'prognose', 'prognoseband', 'markt', 'datenanalyse', 'backtest', 'speicher', 'anlagendaten']

for (const theme of ['light', 'dark'] as const) {
  test(`a11y ${theme}: keine kritischen oder ernsten Verstöße`, async ({ page }) => {
    test.setTimeout(240_000)
    await page.addInitScript((t) => localStorage.setItem('fldos_theme', t), theme)
    const found: string[] = []
    for (const p of PATHS) {
      await page.goto(`/#/${p}`)
      await page.reload()
      await expect(page.locator('.content h1')).toBeVisible()
      await settled(page)
      const r = await new AxeBuilder({ page }).include('body').analyze()
      for (const v of r.violations.filter((x) => x.impact === 'critical' || x.impact === 'serious')) {
        found.push(`${p}: ${v.id} (${v.impact}) ×${v.nodes.length} — ${v.nodes[0]?.target.join(' ')}`)
      }
    }
    expect(found).toEqual([])
  })
}

test('Enno-Panel: Bedienelemente beschriftet und per Tastatur erreichbar', async ({ page }) => {
  await page.goto('/#/cockpit')
  await page.getByRole('tab', { name: /Enno/ }).click()
  const r = await new AxeBuilder({ page }).include('.sidebar').analyze()
  expect(r.violations.filter((x) => x.impact === 'critical' || x.impact === 'serious').map((v) => `${v.id}: ${v.nodes[0]?.target}`)).toEqual([])
  await page.getByPlaceholder('Frag Enno …').fill('Hallo')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Senden' })).toBeFocused()
})
