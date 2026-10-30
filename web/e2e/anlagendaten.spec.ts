// Anlagendaten: Import per Knopf (JSON/CSV) und per Drag & Drop, Speichern, Persistenz, Ablehnung ungültiger Werte.
import { expect, gasStart, test, whatif } from './fixtures'

test.afterEach(async ({ page }) => {
  await page.request.put('/fld-api/plant-config', { data: { params: {} } }) // geteilten Zustand zurücksetzen
})

const row = (page: import('@playwright/test').Page, key: string) =>
  page.locator('.content table tbody tr', { has: page.getByText(key, { exact: true }) })

test('JSON-Import füllt Felder, Speichern schickt PUT, Abweichung wird angezeigt und übersteht Neuladen', async ({ page }) => {
  const cfg = await (await page.request.get('/fld-api/plant-config')).json()
  await page.goto('/#/anlagendaten')
  await expect(page.locator('.content table tbody tr')).toHaveCount(Object.keys(cfg.defaults).length)
  for (const k of cfg.fixed) await expect(row(page, k).locator('input')).toHaveCount(0)  // Zeitraster gesperrt
  await page.locator('input[type=file]').setInputFiles({ name: 'anlage.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ eta_el: 0.4, p_bhkw_mw: 1.2 })) })
  await expect(page.getByText('2 Werte aus anlage.json übernommen')).toBeVisible()
  await expect(row(page, 'eta_el').locator('input')).toHaveValue('0.4')
  await expect(row(page, 'eta_el').locator('td').nth(3)).toHaveText('-4,8 %')

  const [put] = await Promise.all([
    page.waitForRequest((r) => r.url().endsWith('/fld-api/plant-config') && r.method() === 'PUT'),
    page.getByRole('button', { name: 'Speichern' }).click(),
  ])
  expect(put.postDataJSON()).toEqual({ params: { eta_el: 0.4, p_bhkw_mw: 1.2 } })
  await expect(page.getByText('Gespeichert: 2 Anlagenwerte, 2 weichen vom Modell ab.')).toBeVisible()

  await page.reload()
  await expect(row(page, 'p_bhkw_mw').locator('input')).toHaveValue('1.2')
})

test('CSV-Import (Semikolon, Dezimalkomma) und Eingabe per Hand', async ({ page }) => {
  await page.goto('/#/anlagendaten')
  await page.locator('input[type=file]').setInputFiles({ name: 'anlage.csv', mimeType: 'text/csv', buffer: Buffer.from('parameter;wert\nstart_cost_eur;75\neta_ptx;0,65\n') })
  await expect(row(page, 'start_cost_eur').locator('input')).toHaveValue('75')
  await expect(row(page, 'eta_ptx').locator('input')).toHaveValue('0.65')
  await row(page, 'heat_credit_eur_mwh').locator('input').fill('20')
  const [put] = await Promise.all([
    page.waitForRequest((r) => r.url().endsWith('/fld-api/plant-config') && r.method() === 'PUT'),
    page.getByRole('button', { name: 'Speichern' }).click(),
  ])
  expect(put.postDataJSON().params).toEqual({ start_cost_eur: 75, eta_ptx: 0.65, heat_credit_eur_mwh: 20 })
})

test('Drag & Drop einer Datei auf die Seite importiert sie', async ({ page }) => {
  await page.goto('/#/anlagendaten')
  const zone = page.getByText('Datei hierher ziehen')
  await expect(zone).toBeVisible()
  const dt = await page.evaluateHandle(() => {
    const d = new DataTransfer()
    d.items.add(new File([JSON.stringify({ min_load: 0.45 })], 'drop.json', { type: 'application/json' }))
    return d
  })
  await zone.dispatchEvent('dragenter', { dataTransfer: dt })
  await zone.dispatchEvent('dragover', { dataTransfer: dt })
  await zone.dispatchEvent('drop', { dataTransfer: dt })
  await expect(page.getByText('1 Werte aus drop.json übernommen')).toBeVisible()
  await expect(row(page, 'min_load').locator('input')).toHaveValue('0.45')
})

test('Ungültige Werte: Server lehnt ab, UI zeigt den Grund, nichts wird gespeichert', async ({ page, guard }) => {
  guard.allowApiErrors(/plant-config/)
  guard.allowApiErrors(/422 \(Unprocessable/)
  await page.goto('/#/anlagendaten')
  await row(page, 'eta_el').locator('input').fill('-1')
  await page.getByRole('button', { name: 'Speichern' }).click()
  await expect(page.getByRole('alert')).toContainText('negative Werte nicht zulässig: eta_el')

  await page.locator('input[type=file]').setInputFiles({ name: 'x.json', mimeType: 'application/json', buffer: Buffer.from('{"gibt_es_nicht": 1}') })
  await row(page, 'eta_el').locator('input').fill('')
  await page.getByRole('button', { name: 'Speichern' }).click()
  await expect(page.getByRole('alert')).toContainText('unbekannte Parameter: gibt_es_nicht')
  const cfg = await (await page.request.get('/fld-api/plant-config')).json()
  expect(cfg.override).toEqual({})
})

test('kaputte Datei: verständliche Meldung statt Absturz', async ({ page }) => {
  await page.goto('/#/anlagendaten')
  await page.locator('input[type=file]').setInputFiles({ name: 'kaputt.json', mimeType: 'application/json', buffer: Buffer.from('{ kaputt') })
  await expect(page.getByRole('alert')).toContainText('Datei nicht lesbar (kaputt.json)')
})

test('Durchstich: gespeicherter Anlagenwert verändert das Ergebnis auf Was-wäre-wenn, Zurücksetzen stellt es wieder her', async ({ page }) => {
  const netOf = async () => {
    await page.goto('/#/anlagendaten')  // erst weg, sonst lädt dieselbe Route nicht neu
    const gas = await gasStart(page)
    const [r] = await Promise.all([page.waitForResponse(whatif((b) => b.gas === gas)), page.goto('/#/was-waere-wenn')])
    const out = await r.json()
    await expect(page.locator('.kpi', { has: page.getByText('Netto inkl. EEG', { exact: true }) }).locator('.kpi-value')).toHaveText(`${(out.net_eeg_eur ?? out.net_eur).toLocaleString('de-DE', { maximumFractionDigits: 0 })} €`)
    return (out.net_eeg_eur ?? out.net_eur) as number
  }
  const before = await netOf()

  await page.goto('/#/anlagendaten')
  await row(page, 'eta_el').locator('input').fill('0.36')
  await page.getByRole('button', { name: 'Speichern' }).click()
  await expect(page.getByText('Gespeichert: 1 Anlagenwerte')).toBeVisible()
  const after = await netOf()
  expect(Math.abs(after - before), 'Wirkungsgrad 0,36 statt 0,42 muss das Ergebnis ändern').toBeGreaterThan(1)

  await page.request.put('/fld-api/plant-config', { data: { params: {} } })
  expect(await netOf()).toBeCloseTo(before, 6)
})

test('unmögliche Anlage: Server lehnt mit Begründung ab', async ({ page, guard }) => {
  guard.allowApiErrors(/plant-config/)
  guard.allowApiErrors(/422 \(Unprocessable/)
  await page.goto('/#/anlagendaten')
  await row(page, 'heat_min_runtime_slots').locator('input').fill('96')
  await row(page, 'full_hours_per_day').locator('input').fill('1')
  await page.getByRole('button', { name: 'Speichern' }).click()
  await expect(page.getByRole('alert')).toContainText('kein Fahrplan möglich')
})
