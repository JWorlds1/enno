// Erlöse, Prognose, Nachweis: Zeitraum-Umschalter, Budget-Knöpfe, Datenanalyse-Zoom — UI ↔ API.
import { api, de, expect, gasStart, kpi, settled, test } from './fixtures'

async function switchDays(page: import('@playwright/test').Page, endpoint: string, label: string, days: number) {
  const [resp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes(`/fld-api/${endpoint}`) && r.url().includes(`days=${days}`), { timeout: 110_000 }),
    page.getByRole('button', { name: label, exact: true }).click(),
  ])
  expect(resp.status()).toBe(200)
  await expect(page.getByRole('button', { name: label, exact: true })).toHaveAttribute('aria-pressed', 'true')
  return resp.json()
}

test('Erlös-Stapel: 7/14 Tage, Tabelle und Karten folgen der Antwort', async ({ page }) => {
  test.setTimeout(180_000)
  await page.goto('/#/erloes-stapel')
  await settled(page)
  const r = await switchDays(page, 'revenue-stack', '14 Tage', 14)
  await expect(page.locator('.content table tbody tr')).toHaveCount(14)
  await expect(kpi(page, 'Ø Mehrerlös / Tag')).toHaveText(`+${de(r.avg_uplift)} €`)
  await switchDays(page, 'revenue-stack', '7 Tage', 7)
  await expect(page.locator('.content table tbody tr')).toHaveCount(7)
})

test('Plasma: 10/30 Tage, Befund-Text passt zum Ergebnis', async ({ page }) => {
  test.setTimeout(180_000)
  await page.goto('/#/plasma')
  await settled(page)
  const r = await switchDays(page, 'plasma-compare', '30 Tage', 30)
  await expect(page.locator('.content table tbody tr')).toHaveCount(30)
  await expect(kpi(page, 'Mehrwert Plasma')).toHaveText(`${r.uplift_pyro >= 0 ? '+' : ''}${de(r.uplift_pyro)} €`)
  const winner = r.uplift_pyro > r.uplift_electro ? 'liegt Plasma-Pyrolyse vorn' : 'liegt die Elektrolyse vorn'
  await expect(page.locator('.note', { hasText: 'Befund' })).toContainText(winner)
  await switchDays(page, 'plasma-compare', '10 Tage', 10)
})

test('EEG-Budget: jeder Budget-Knopf fragt das Backend und zeigt die Antwort', async ({ page }) => {
  await page.goto('/#/eeg')
  await settled(page)
  for (const h of [657, 1095, 876]) {
    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes(`/fld-api/eeg-budget?annual_hours=${h}`)),
      page.getByRole('button', { name: `${h} h`, exact: true }).click(),
    ])
    const d = await resp.json()
    await expect(kpi(page, 'Jahres-Volllaststunden')).toHaveText(`${h} h`)
    await expect(page.getByText(`≈ ${d.affordable_days} beste Betriebstage`)).toBeVisible()
  }
})

test('CDR-Preis: Break-even entspricht /cdr-sensitivity', async ({ page }) => {
  const gas = await gasStart(page)  // die Seite rechnet mit Biomethan heute, wie Was-wäre-wenn
  const d = await api<{ break_even_co2: number | null }>(page, `/cdr-sensitivity?gas=${gas}&h2=100`)
  await page.goto('/#/cdr')
  await settled(page)
  await expect(page.getByText(d.break_even_co2 != null ? `${d.break_even_co2} €/t` : '—').first()).toBeVisible()
})

test('Prognoseband: 3/7/14 Tage, Abdeckungs-Karten = Antwort', async ({ page }) => {
  await page.goto('/#/prognoseband')
  await settled(page)
  for (const [label, days] of [['3 Tage', 3], ['14 Tage', 14], ['7 Tage', 7]] as const) {
    const r = await switchDays(page, 'forecast-band', label, days)
    expect(r.series.length).toBe(days * 96)
    await expect(kpi(page, 'ACI (adaptiv)')).toHaveText(`${de(r.coverage.aci * 100)} %`)
    await expect(kpi(page, 'Roh (Quantile)')).toHaveText(`${de(r.coverage.raw * 100)} %`)
  }
})

test('Speicher & MPC: 7/14/30 Tage, Summen = Antwort', async ({ page }) => {
  test.setTimeout(180_000)
  await page.goto('/#/speicher')
  await settled(page)
  for (const [label, days] of [['7 Tage', 7], ['30 Tage', 30], ['14 Tage', 14]] as const) {
    const r = await switchDays(page, 'mpc', label, days)
    expect(r.days.length).toBe(days)
    await expect(kpi(page, 'MPC')).toHaveText(`${de(r.total_mpc)} €`)
    await expect(kpi(page, 'Tagesisoliert')).toHaveText(`${de(r.total_base)} €`)
  }
})

test('Backtest: Kennzahlen entsprechen /backtest', async ({ page }) => {
  const bt = await api<{ up_fc: number; ok: boolean }[]>(page, '/backtest')
  await page.goto('/#/backtest')
  await settled(page)
  await expect(page.getByText(`${bt.length}`, { exact: true }).first()).toBeVisible()
  const total = bt.reduce((a, x) => a + x.up_fc, 0)
  await expect(page.getByText(`${de(total)} €`).first()).toBeVisible()
})

test('Datenanalyse: alle Abbildungen laden, Klick zoomt, Klick schließt; Heatmap da', async ({ page }) => {
  const figs = await api<{ name: string }[]>(page, '/figures')
  await page.goto('/#/datenanalyse')
  const imgs = page.locator('.content img[alt]')
  await expect(imgs).toHaveCount(figs.length)
  for (let i = 0; i < figs.length; i++) {
    await imgs.nth(i).scrollIntoViewIfNeeded()
    await expect.poll(() => imgs.nth(i).evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true)
  }
  await imgs.first().click()
  const overlay = page.locator('div[style*="position: fixed"] img')
  await expect(overlay).toBeVisible()
  await overlay.click()
  await expect(overlay).toHaveCount(0)
  await expect(page.getByText('Preis-Heatmap')).toBeVisible()
})

test('Markt und Prognose-Güte laden ihre Daten', async ({ page }) => {
  await page.goto('/#/markt')
  await settled(page)
  await expect(page.locator('.content canvas')).toHaveCount(2)
  await page.goto('/#/prognose')
  await settled(page)
  const fc = await api<unknown[]>(page, '/forecast')
  await expect(kpi(page, 'Punkte')).toHaveText(`${fc.length}`)
})

test('Fahrplan: eine Zeile je Marktstunde, Strategie im Klartext', async ({ page }) => {
  const dec = await api<{ label: string }>(page, '/decision')
  const rec = await api<{ slots: unknown[] }>(page, '/recommendation')
  await page.goto('/#/empfehlung')
  await settled(page)
  await expect(kpi(page, 'Strategie')).toHaveText(dec.label)
  await expect(page.locator('.content table tbody tr')).toHaveCount(rec.slots.length / 4)  // 24, an Umstellungstagen 23/25
  await expect(page.locator('.content table tbody tr').first()).toContainText('00:00')
})
