// Planung: jeder Regler/Knopf löst den richtigen Request aus, die UI zeigt genau die Antwort.
import { api, de, expect, gasStart, kpi, settled, test, whatif } from './fixtures'

const signed = (v: number) => `${v >= 0 ? '+' : ''}${de(v)} €`

test('Was-wäre-wenn: Startwerte aus Markt, Regler, Technik und alle fünf Optimierer rechnen live', async ({ page }) => {
  const gas = await gasStart(page)
  const [first] = await Promise.all([page.waitForResponse(whatif((b) => b.gas === gas)), page.goto('/#/was-waere-wenn')])
  expect(first.request().postDataJSON()).toEqual({ gas, h2: 100, co2: 79, mode: 'electro', algo: 'whatif' })
  const base = await first.json()
  await expect(kpi(page, 'Mehrerlös')).toHaveText(signed(base.uplift_eur))
  // Startwerte = Anlage wie im Cockpit (BHKW + Elektrolyseur) → derselbe Mehrerlös wie dort
  const rec = await api<{ kpis: Record<string, number | string> }>(page, '/recommendation')
  const dec = await api<{ strategy: string; scores: Record<string, number> }>(page, '/decision')
  if (rec.kpis.price_basis === 'Prognose' && dec.strategy !== 'REGELENERGIE_RESERVE') {
    expect(Math.round(base.uplift_eur)).toBe(Math.round(rec.kpis.expected_uplift_eur as number))
  } else {
    // nach der Auktion: Neuplanung mit bekannten Preisen ≥ Gebotsplan (nur Spot) zu denselben Preisen; die Seite erklärt den Unterschied
    expect(Math.round(base.uplift_eur)).toBeGreaterThanOrEqual(Math.round(dec.scores.SPOT_FLEX) - 1)
    await expect(page.locator('.note', { hasText: 'Bezug zum Cockpit' })).toContainText(`${signed(rec.kpis.expected_uplift_eur as number)}`)
  }

  const sliders = page.locator('input[type=range]')
  for (const c of [{ idx: 0, value: '100', key: 'gas' }, { idx: 1, value: '150', key: 'h2' }, { idx: 2, value: '200', key: 'co2' }] as const) {
    const [resp] = await Promise.all([page.waitForResponse(whatif((b) => b[c.key] === Number(c.value))), sliders.nth(c.idx).fill(c.value)])
    const out = await resp.json()
    expect(out.status).toBe('Optimal')
    await expect(kpi(page, 'Netto inkl. EEG')).toHaveText(`${de(out.net_eeg_eur ?? out.net_eur)} €`)
    await expect(kpi(page, 'Mehrerlös')).toHaveText(signed(out.uplift_eur))
  }
  for (const [label, mode] of [['nur BHKW', 'none'], ['Plasma', 'plasma'], ['Elektrolyse', 'electro']] as const) {
    const [resp] = await Promise.all([page.waitForResponse(whatif((b) => b.mode === mode)), page.getByRole('button', { name: label, exact: true }).click()])
    const out = await resp.json()
    await expect(kpi(page, 'Wasserstoff')).toHaveText(`${de(out.h2_mwh, 2)} MWh`)
    if (mode === 'none') expect(out.h2_mwh).toBe(0)
  }
  for (const algo of ['schedule', 'coopt', 'stochastic', 'cvar', 'whatif']) {
    const [resp] = await Promise.all([page.waitForResponse(whatif((b) => b.algo === algo)), page.locator('select').selectOption(algo)])
    const out = await resp.json()
    expect(out.status, algo).toBe('Optimal')
    await expect(kpi(page, 'Mehrerlös')).toHaveText(signed(out.uplift_eur))
  }
  await expect(page.getByText('Masterarbeit')).toHaveCount(0)
})

test('Was-wäre-wenn: Szenarien merken, vergleichen, laden, entfernen — bleiben nach Neuladen', async ({ page }) => {
  const gas = await gasStart(page)
  const [first] = await Promise.all([page.waitForResponse(whatif((b) => b.gas === gas)), page.goto('/#/was-waere-wenn')])
  const a = await first.json()
  await page.getByRole('button', { name: 'Szenario merken' }).click()
  const [resp] = await Promise.all([page.waitForResponse(whatif((b) => b.mode === 'none')), page.getByRole('button', { name: 'nur BHKW', exact: true }).click()])
  const b = await resp.json()
  await expect(page.getByRole('button', { name: 'Szenario merken' })).toBeEnabled()
  await page.getByRole('button', { name: 'Szenario merken' }).click()
  const rows = page.locator('table tbody tr')
  await expect(rows).toHaveCount(2)
  await expect(rows.nth(0)).toContainText(signed(a.uplift_eur))
  await expect(rows.nth(1)).toContainText(signed(b.uplift_eur))
  const net = (o: { net_eeg_eur?: number | null; net_eur: number }) => Math.round(o.net_eeg_eur ?? o.net_eur)
  await expect(rows.nth(0)).toContainText(`${de(a.net_eeg_eur ?? a.net_eur)} €`)  // Tabelle = Karte „Netto inkl. EEG“
  await expect(page.locator('table tbody tr', { hasText: '★' })).toHaveCount(net(a) === net(b) ? 0 : 1)

  const [load] = await Promise.all([page.waitForResponse(whatif((x) => x.mode === 'electro')), rows.nth(0).getByRole('button', { name: 'Laden' }).click()])
  expect(load.request().postDataJSON().gas).toBe(gas)
  await page.reload()
  await expect(page.locator('table tbody tr')).toHaveCount(2)
  await page.getByRole('button', { name: 'Szenario 2 entfernen' }).click()
  await expect(page.locator('table tbody tr')).toHaveCount(1)
  await page.getByRole('button', { name: 'Alle löschen' }).click()
  await expect(page.getByText('Szenarien im Vergleich')).toHaveCount(0)
})

test('Was-wäre-wenn: schnelles Schieben löst nur EINE Rechnung aus (Entprellung)', async ({ page, guard }) => {
  const gas = await gasStart(page)
  await Promise.all([page.waitForResponse(whatif((b) => b.gas === gas)), page.goto('/#/was-waere-wenn')])
  const before = guard.apiCalls.filter((c) => c.url.endsWith('/whatif')).length
  const slider = page.locator('input[type=range]').first()
  for (const v of ['80', '85', '90', '95']) await slider.fill(v)
  await page.waitForResponse(whatif((b) => b.gas === 95))
  await page.waitForTimeout(500)
  const calls = guard.apiCalls.filter((c) => c.url.endsWith('/whatif')).slice(before)
  expect(calls.map((c) => JSON.parse(c.body!).gas)).toEqual([95])
})

test('Was-wäre-wenn: eine langsame ältere Rechnung überschreibt nicht die letzte Eingabe', async ({ page }) => {
  const gas = await gasStart(page)
  await Promise.all([page.waitForResponse(whatif((b) => b.gas === gas)), page.goto('/#/was-waere-wenn')])
  // die Rechnung für 60 €/MWh kommt 3 s zu spät — erst nach der für 150 €/MWh
  await page.route('**/fld-api/whatif', async (route) => {
    if (route.request().postDataJSON().gas === 60) await new Promise((r) => setTimeout(r, 3000))
    await route.continue()
  })
  const slider = page.locator('input[type=range]').first()
  const slow = page.waitForResponse(whatif((b) => b.gas === 60))
  await slider.fill('60')
  await page.waitForTimeout(500)  // nach der Entprellung: 60 ist unterwegs
  const [last] = await Promise.all([page.waitForResponse(whatif((b) => b.gas === 150)), slider.fill('150')])
  const want = await last.json()
  await slow
  await page.waitForTimeout(300)
  await expect(kpi(page, 'Netto inkl. EEG')).toHaveText(`${de(want.net_eeg_eur ?? want.net_eur)} €`)
})

test('Sensitivität: Regler und Pfad ändern die Anfrage, Tornado und Karten zeigen die Antwort', async ({ page, guard }) => {
  await page.goto('/#/sensitivitaet')
  await settled(page)
  const [resp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes('/fld-api/sensitivity') && r.url().includes('gas=100')),
    page.locator('input[type=range]').first().fill('100'),
  ])
  const out = await resp.json()
  await expect(kpi(page, 'Netto-Tageserlös (Basis)')).toHaveText(`${de(out.base_net)} €`)
  await expect(kpi(page, 'Stärkster Hebel')).toHaveText(out.bars[0].label)

  for (const [label, mode] of [['Nur BHKW', 'none'], ['Plasma', 'plasma'], ['Elektrolyse', 'electro']] as const) {
    const [r] = await Promise.all([
      page.waitForResponse((x) => x.url().includes('/fld-api/sensitivity') && x.url().includes(`mode=${mode}`)),
      page.getByRole('button', { name: label, exact: true }).click(),
    ])
    const o = await r.json()
    expect(o.mode).toBe(mode)
    await expect(kpi(page, 'Netto-Tageserlös (Basis)')).toHaveText(`${de(o.base_net)} €`)
  }
  const h2 = page.locator('input[type=range]').nth(1)
  for (const v of ['120', '130', '140']) await h2.fill(v)
  await page.waitForResponse((r) => r.url().includes('/fld-api/sensitivity') && r.url().includes('h2=140'))
  await page.waitForTimeout(600)
  const h2Calls = guard.apiCalls.filter((c) => c.url.includes('/sensitivity') && /h2=1[234]0/.test(c.url))
  expect(h2Calls.length, 'Entprellung: nur der letzte Wert wird gerechnet').toBe(1)
})

test('Risiko: Karten und Tabelle entsprechen /risk', async ({ page }) => {
  const r = await api<{ rp: number; eev: number; ws: number; vss: number; evpi: number; frontier: unknown[] }>(page, '/risk')
  await page.goto('/#/risiko')
  await settled(page)
  await expect(kpi(page, 'Stochastisch (RP)')).toHaveText(`${de(r.rp)} €`)
  await expect(kpi(page, 'Deterministisch (EEV)')).toHaveText(`${de(r.eev)} €`)
  await expect(kpi(page, 'Perfekte Info (WS)')).toHaveText(`${de(r.ws)} €`)
  await expect(kpi(page, 'Wert der Stochastik')).toHaveText(`${de(r.vss, 1)} €`)
  await expect(page.locator('.content table tbody tr')).toHaveCount(r.frontier.length)
})

test('Pareto: Karten entsprechen /pareto', async ({ page }) => {
  const r = await api<{ slope_eur_t: number; eua: number; day: string; front: unknown[] }>(page, '/pareto')
  await page.goto('/#/pareto')
  await settled(page)
  await expect(kpi(page, 'Vermeidungskosten')).toHaveText(`${de(r.slope_eur_t)} €/t`)
  await expect(kpi(page, 'EUA-Preis')).toHaveText(`${de(r.eua)} €/t`)
  await expect(kpi(page, 'Analysetag')).toHaveText(r.day)
})

test('Splitter: Verwertung, eigene Preise und Preisrechner — UI zeigt genau die Antwort', async ({ page }) => {
  const isSplit = (q: string[]) => (r: import('@playwright/test').Response) => r.url().includes('/fld-api/splitter?') && q.every((x) => r.url().includes(x))
  await page.goto('/#/splitter')
  await settled(page)
  const vp = await api<{ h2: { eur_kg: number }; carbon: Record<string, { eur_kg: number | null }> }>(page, '/value-prices')
  await expect(page.locator('.content table').first()).toContainText(`${de(vp.h2.eur_kg, 2)} €/kg`)
  const cdr = (vp.carbon.cdr as unknown as { check: { status: string } }).check
  await expect(page.locator('.content table').first().locator('tr', { hasText: 'Entnahme-Zertifikat' })).toContainText(cdr.status)
  // Jahresrechnung, Optimierer-Plan und Gebote zeigen genau die API
  const y = await api<{ switches_per_year: number; bhkw_share_pct: number; bids: { capture_pct: number } }>(page, '/splitter-year?carbon=co2')
  await expect(kpi(page, 'Umschaltungen/Jahr')).toHaveText(de(y.switches_per_year))
  await expect(kpi(page, 'BHKW-Anteil')).toHaveText(`${de(y.bhkw_share_pct)} %`)
  await expect(kpi(page, 'Vom Bestmöglichen')).toHaveText(`${de(y.bids.capture_pct, 1)} %`)
  // Tagesnachweis: Karten und Tabelle zeigen genau /splitter-proof
  const pf = await api<{ days: { day: string; status: string; capture_pct: number | null }[]; summary: { streak_days: number; settled_days: number; missing_days: number; late_days: number; capture_pct: number } }>(page, '/splitter-proof?carbon=co2')
  await expect(kpi(page, 'Tage in Folge')).toHaveText(`${pf.summary.streak_days}`)
  await expect(kpi(page, 'Abgerechnet')).toHaveText(`${pf.summary.settled_days} Tage`)
  await expect(kpi(page, 'Lücken')).toHaveText(`${pf.summary.missing_days + pf.summary.late_days}`)
  await expect(kpi(page, 'Erreicht')).toHaveText(`${de(pf.summary.capture_pct, 1)} %`)
  const last = pf.days[pf.days.length - 1]
  await expect(page.locator('.content tr', { hasText: last.day }).first()).toContainText(last.status)
  const pl = await api<{ plasma_gas_mwh: number }>(page, '/splitter-plan?carbon=co2')
  await expect(kpi(page, 'Gas ins Plasma')).toHaveText(`${de(pl.plasma_gas_mwh, 1)} MWh`)
  const cv = await api<{ months: { month: string; threshold: Record<string, number | null> }[] }>(page, '/value-curve')
  const first = cv.months.find((m) => m.threshold.co2 != null)
  if (first) await expect(page.locator('.content tr', { hasText: first.month })).toContainText(`${de(first.threshold.co2 as number)} €/MWh`)
  await expect(page.getByRole('link', { name: 'Gebote herunterladen (CSV)' })).toHaveAttribute('href', '/fld-api/splitter-bids.csv?carbon=co2')
  for (const [label, carbon] of [['Entnahme-Zertifikat', 'cdr'], ['CO₂-Wert', 'co2']] as const) {
    const [resp] = await Promise.all([page.waitForResponse(isSplit([`carbon=${carbon}`])), page.getByRole('button', { name: label, exact: true }).click()])
    const d = await resp.json()
    expect(d.c_eur_kg).toBeCloseTo(vp.carbon[carbon].eur_kg as number, 6)
    await expect(kpi(page, 'Strom lohnt ab')).toHaveText(`${de(d.threshold_eur_mwh)} €/MWh`)
    await expect(kpi(page, 'Strom-Viertelstunden')).toHaveText(`${d.strom_slots} von ${d.slots.length}`)
    await expect(kpi(page, 'Erlös Splitter')).toHaveText(`${de(d.revenue.splitter)} €`)
  }
  const [own] = await Promise.all([page.waitForResponse(isSplit(['h2=7', 'c=1.5'])), (async () => {
    await page.getByLabel('Eigener H₂-Preis (€/kg)').fill('7')
    await page.getByLabel('Eigener Kohlenstoffpreis (€/kg)').fill('1,5')
  })()])
  const o = await own.json()
  expect(o.own_prices).toBe(true)
  await expect(kpi(page, 'Strom lohnt ab')).toHaveText(`${de(o.threshold_eur_mwh)} €/MWh`)
  await Promise.all([page.waitForResponse(isSplit(['carbon=co2'])), page.getByRole('button', { name: 'Preisrechner verwenden' }).click()])
  if (vp.carbon.black.eur_kg == null) {  // ohne Öldaten keine Schätzung: Hinweis statt Request
    await page.getByRole('button', { name: 'Industrieruß', exact: true }).click()
    await expect(page.locator('.note', { hasText: 'Keine Öldaten' })).toBeVisible()
  } else {
    const [b] = await Promise.all([page.waitForResponse(isSplit(['carbon=black'])), page.getByRole('button', { name: 'Industrieruß', exact: true }).click()])
    await expect(kpi(page, 'Strom lohnt ab')).toHaveText(`${de((await b.json()).threshold_eur_mwh)} €/MWh`)
  }
})
