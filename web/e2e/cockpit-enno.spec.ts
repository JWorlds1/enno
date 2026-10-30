// Cockpit (UI ↔ API-Werte, alle Knöpfe) und Enno (Senden, Vorschläge, Aktionen, Sitzung, Fehlerfall).
import { api, de, expect, kpi, settled, test } from './fixtures'

interface Rec { target_day: string; kpis: Record<string, number> }
interface Dec { label: string; strategy: string; summary: string | null }
interface Val { per_year_eur: number; pct_vs_flat: number; capture_pct: number; days: number }

test('Cockpit zeigt genau die Werte aus /recommendation, /decision und /value', async ({ page }) => {
  const rec = await api<Rec & { kpis: Record<string, number | string> }>(page, '/recommendation')
  const dec = await api<Dec>(page, '/decision')
  const val = await api<Val>(page, '/value')
  const k = rec.kpis as Record<string, number>
  await page.goto('/#/cockpit')
  await settled(page)
  await expect(page.locator('.hero h2')).toHaveText(dec.label)
  if (dec.summary) await expect(page.locator('.hero')).toContainText(dec.summary)
  await expect(page.locator('.hero .big')).toHaveText(`≈ ${de(Math.round(val.per_year_eur / 1000) * 1000)} €`)
  await expect(page.locator('.hero')).toContainText(`an ${val.days} Tagen nachgerechnet`)
  // Tageswort wie die Seite: „morgen“ nur für den Liefertag morgen (Marktzeit), sonst Datum
  const today = new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Berlin' })
  const diff = Math.round((Date.parse(`${rec.target_day}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000)
  const when = diff === 1 ? 'morgen' : diff === 0 ? 'heute' : `am ${rec.target_day.split('-').reverse().slice(0, 2).join('.')}.`
  await expect(kpi(page, `Mehr als Dauerbetrieb ${when}`)).toHaveText(`${k.expected_uplift_eur >= 0 ? '+' : ''}${de(k.expected_uplift_eur)} €`)
  await expect(kpi(page, `Strompreis ${when}`)).toHaveText(`${de(k.pred_price_min)}–${de(k.pred_price_max)}`)
  await expect(kpi(page, 'BHKW-Laufzeit')).toHaveText(`${de(k.bhkw_runtime_h, 1)} h`)
  await expect(kpi(page, 'Treffsicherheit')).toHaveText(`${de(val.capture_pct)} %`)
  const basis = rec.kpis.price_basis === 'Auktion' ? 'bewertet zu Auktionspreisen' : 'Gebotsplan auf Preisprognose'
  await expect(page.locator('.hero .eyebrow')).toContainText(basis)
})

test('Cockpit-Knöpfe: Fahrplan, Backtest, Report, „Warum? Frag Enno“', async ({ page, context }) => {
  await page.goto('/#/cockpit')
  await settled(page)
  await page.getByRole('link', { name: 'Fahrplan ansehen' }).click()
  await expect(page).toHaveURL(/#\/empfehlung$/)
  await page.goBack()
  await page.getByRole('link', { name: /Nachweis: Backtest/ }).click()
  await expect(page).toHaveURL(/#\/backtest$/)
  await page.goBack()

  const [report] = await Promise.all([context.waitForEvent('page'), page.getByRole('link', { name: 'Report öffnen' }).click()])
  await report.waitForLoadState()
  expect(report.url()).toContain('/fld-api/report')
  // Tagesbericht (fldos/pipeline/report.py): Titel + Liefertag der aktuellen Empfehlung, Fahrplan-Tabelle mit 24 Stunden
  const rec = await api<{ target_day: string }>(page, '/recommendation')
  const [y, m, d] = rec.target_day.split('-')
  await expect(report).toHaveTitle(`FLD OS · Tagesbericht ${d}.${m}.${y}`)
  await expect(report.locator('table tbody tr')).toHaveCount(24)
  const resp = await page.request.get('/fld-api/report')
  expect(resp.status()).toBe(200)
  expect(resp.headers()['content-type']).toContain('text/html')
  await report.close()

  const chat = page.waitForRequest((r) => r.url().endsWith('/fld-api/chat') && r.method() === 'POST')
  await page.getByRole('button', { name: 'Warum? Frag Enno' }).click()
  const body = (await chat).postDataJSON()
  expect(body).toMatchObject({ message: 'Warum diese Strategie?', page: 'cockpit' })
  const dec = await api<Dec>(page, '/decision')
  await expect(page.locator('.enno-msg.assistant').last()).toContainText(`Ich empfehle ${dec.label}`)
})

test('Enno: Enter sendet, Antwort kommt vom Backend, Sitzung bleibt bestehen, Aktion navigiert', async ({ page }) => {
  await page.goto('/#/backtest')
  await page.getByRole('tab', { name: /Enno/ }).click()
  const input = page.getByPlaceholder('Frag Enno …')
  const send = page.getByRole('button', { name: 'Senden' })
  await expect(send).toBeDisabled()

  await input.fill('Wie gut war der Backtest?')
  await expect(send).toBeEnabled()
  const [r1] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/fld-api/chat')),
    input.press('Enter'),
  ])
  const a1 = await r1.json()
  expect(r1.request().postDataJSON()).toMatchObject({ message: 'Wie gut war der Backtest?', page: 'backtest', session_id: null })
  await expect(input).toHaveValue('')
  await expect(page.locator('.enno-msg.user').last()).toHaveText('Wie gut war der Backtest?')
  await expect(page.locator('.enno-msg.assistant .bubble').last()).toContainText('echte Tage')
  expect(a1.tool_calls.map((t: { name: string }) => t.name)).toContain('get_backtest')

  // Shift+Enter fügt eine Zeile ein statt zu senden
  await input.fill('Zeile 1')
  await input.press('Shift+Enter')
  await expect(page.locator('.enno-msg.user')).toHaveCount(1)
  await input.fill('')

  // zweite Frage über den Senden-Knopf, gleiche Sitzung
  await input.fill('Rechne mit Gaspreis 90')
  const [r2] = await Promise.all([page.waitForResponse((r) => r.url().endsWith('/fld-api/chat')), send.click()])
  expect(r2.request().postDataJSON().session_id).toBe(a1.session_id)
  await expect(page.locator('.enno-msg.assistant .bubble').last()).toContainText('Mit Gas 90 €/MWh')

  // Aktions-Link unter der Antwort navigiert
  await page.locator('.enno-actions a', { hasText: 'Selbst an den Reglern drehen' }).last().click()
  await expect(page).toHaveURL(/#\/was-waere-wenn$/)
  await expect(page.locator('.content h1')).toHaveText('Was-wäre-wenn')
  await expect(page.locator('.enno-msg')).toHaveCount(4) // Gespräch übersteht den Seitenwechsel

  await page.getByRole('button', { name: 'Neu' }).click()
  await expect(page.locator('.enno-msg')).toHaveCount(0)
  await expect(page.locator('.enno-hello')).toBeVisible()
})

test('Enno: jeder Vorschlag auf jeder Seite liefert eine echte Antwort', async ({ page }) => {
  test.setTimeout(240_000)
  const pages = ['cockpit', 'was-waere-wenn', 'sensitivitaet', 'risiko', 'pareto', 'erloes-stapel', 'plasma', 'prognoseband', 'backtest', 'speicher', 'markt', 'anlagendaten']
  for (const p of pages) {
    await page.goto(`/#/${p}`)
    await page.getByRole('tab', { name: /Enno/ }).click()
    const chips = page.locator('.enno-suggest button')
    const n = await chips.count()
    expect(n, `Vorschläge auf ${p}`).toBeGreaterThan(0)
    for (let i = 0; i < n; i++) {
      const text = await chips.nth(i).innerText()
      const [resp] = await Promise.all([page.waitForResponse((r) => r.url().endsWith('/fld-api/chat')), chips.nth(i).click()])
      const body = await resp.json()
      expect(body.reply, `${p}: „${text}“`).not.toContain('noch nicht beantworten')
      await expect(page.locator('.enno-msg.assistant .bubble').last()).not.toBeEmpty()
    }
    await page.getByRole('button', { name: 'Neu' }).click()
  }
})

test('Enno: Backend-Fehler wird verständlich angezeigt, Eingabe bleibt bedienbar', async ({ page, guard }) => {
  guard.allowApiErrors(/\/fld-api\/chat/)
  guard.allowApiErrors(/500 \(Internal Server Error\)/)
  await page.route('**/fld-api/chat', (r) => r.fulfill({ status: 500, body: 'boom' }))
  await page.goto('/#/cockpit')
  await page.getByRole('tab', { name: /Enno/ }).click()
  await page.getByPlaceholder('Frag Enno …').fill('Hallo')
  await page.getByRole('button', { name: 'Senden' }).click()
  await expect(page.locator('.enno-msg.assistant .bubble').last()).toContainText('komme gerade nicht an die Daten')
  await expect(page.getByPlaceholder('Frag Enno …')).toBeEnabled()
})

test('Enno: während der Antwort zeigt er „rechnet …“ und sperrt Doppel-Senden', async ({ page }) => {
  await page.route('**/fld-api/chat', async (r) => { await new Promise((res) => setTimeout(res, 1200)); await r.continue() })
  await page.goto('/#/cockpit')
  await page.getByRole('tab', { name: /Enno/ }).click()
  await page.getByPlaceholder('Frag Enno …').fill('Hallo')
  await page.getByRole('button', { name: 'Senden' }).click()
  await expect(page.locator('.enno-sub')).toContainText('rechnet')
  await expect(page.locator('.typing')).toBeVisible()
  await expect(page.locator('.enno-suggest button').first()).toBeDisabled()
  await expect(page.locator('.typing')).toHaveCount(0)
  await expect(page.locator('.enno-sub')).toContainText('bereit')
})
