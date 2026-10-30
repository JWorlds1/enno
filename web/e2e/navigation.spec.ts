// Shell: jede Seite über die Leiste erreichbar, Gruppen, Reiter, Theme, Status, Mobil.
import { api, expect, settled, test } from './fixtures'

const PAGES: { group: string; label: string; path: string; h1: string; charts: number }[] = [
  { group: 'Betrieb', label: 'Cockpit', path: 'cockpit', h1: 'Cockpit', charts: 1 },
  { group: 'Betrieb', label: 'Fahrplan', path: 'empfehlung', h1: 'Fahrplan', charts: 0 },
  { group: 'Planung', label: 'Was-wäre-wenn', path: 'was-waere-wenn', h1: 'Was-wäre-wenn', charts: 1 },
  { group: 'Planung', label: 'Splitter', path: 'splitter', h1: 'Splitter: Strom oder H₂ + Kohlenstoff', charts: 4 },
  { group: 'Planung', label: 'Sensitivität', path: 'sensitivitaet', h1: 'Sensitivität', charts: 1 },
  { group: 'Planung', label: 'Risiko', path: 'risiko', h1: 'Risiko & Robustheit', charts: 1 },
  { group: 'Planung', label: 'Erlös ↔ CO₂', path: 'pareto', h1: 'Erlös ↔ CO₂', charts: 1 },
  { group: 'Erlöse & Technologie', label: 'Erlös-Stapel', path: 'erloes-stapel', h1: 'Erlös-Stapel', charts: 1 },
  { group: 'Erlöse & Technologie', label: 'Plasma vs. Elektrolyse', path: 'plasma', h1: 'Plasma vs. Elektrolyse', charts: 1 },
  { group: 'Erlöse & Technologie', label: 'CDR-Preis', path: 'cdr', h1: 'CDR-Preis-Sensitivität', charts: 2 },
  { group: 'Erlöse & Technologie', label: 'EEG-Jahresbudget', path: 'eeg', h1: 'EEG-Jahresbudget', charts: 1 },
  { group: 'Prognose & Markt', label: 'Prognose-Güte', path: 'prognose', h1: 'Prognose-Güte', charts: 1 },
  { group: 'Prognose & Markt', label: 'Prognoseband', path: 'prognoseband', h1: 'Prognoseband', charts: 2 },
  { group: 'Prognose & Markt', label: 'Markt', path: 'markt', h1: 'Markt-Kontext', charts: 2 },
  { group: 'Prognose & Markt', label: 'Datenanalyse', path: 'datenanalyse', h1: 'Datenanalyse', charts: 0 },
  { group: 'Nachweis', label: 'Backtest', path: 'backtest', h1: 'Nachweis / Backtest', charts: 1 },
  { group: 'Nachweis', label: 'Schattenbetrieb', path: 'schattenbetrieb', h1: 'Schattenbetrieb', charts: 0 },
  { group: 'Nachweis', label: 'Speicher & MPC', path: 'speicher', h1: 'Speicher & MPC', charts: 2 },
  { group: 'Anlage', label: 'Anlagendaten', path: 'anlagendaten', h1: 'Anlagendaten', charts: 0 },
]

test('jede Seite ist über die Leiste erreichbar, lädt Daten und zeigt ihre Diagramme', async ({ page }) => {
  await page.goto('/#/cockpit')
  const nav = page.getByRole('navigation', { name: 'Navigation' })
  for (const p of PAGES) {
    const head = nav.getByRole('button', { name: p.group, exact: true })
    if ((await head.getAttribute('aria-expanded')) !== 'true') await head.click()
    await nav.getByRole('link', { name: p.label, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`#/${p.path}$`))
    await expect(page.locator('.content h1')).toHaveText(p.h1)
    await expect(nav.getByRole('link', { name: p.label, exact: true })).toHaveAttribute('aria-current', 'page')
    await expect(page.locator('.crumb strong')).toHaveText(p.label)
    await settled(page)
    if (p.charts) await expect(page.locator('.content canvas')).toHaveCount(p.charts)
    await expect(page.locator('.note-warn', { hasText: 'nicht erreichbar' })).toHaveCount(0)
  }
})

test('Gruppen klappen auf und zu, die aktive Gruppe ist beim Laden offen', async ({ page }) => {
  await page.goto('/#/risiko')
  const nav = page.getByRole('navigation', { name: 'Navigation' })
  const planung = nav.getByRole('button', { name: 'Planung', exact: true })
  await expect(planung).toHaveAttribute('aria-expanded', 'true')
  await expect(nav.getByRole('button', { name: 'Nachweis', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await planung.click()
  await expect(planung).toHaveAttribute('aria-expanded', 'false')
  await expect(nav.getByRole('link', { name: 'Sensitivität' })).toHaveCount(0)
  await planung.click()
  await expect(nav.getByRole('link', { name: 'Sensitivität' })).toBeVisible()
})

test('Reiter Module/Enno, Enno-Teaser und Deep-Link #/assistent', async ({ page }) => {
  await page.goto('/#/cockpit')
  const tabs = page.getByRole('tablist')
  await tabs.getByRole('tab', { name: /Enno/ }).click()
  await expect(page.getByPlaceholder('Frag Enno …')).toBeVisible()
  await expect(page.locator('.sidebar')).toHaveClass(/wide/)
  await tabs.getByRole('tab', { name: 'Module' }).click()
  await expect(page.getByRole('button', { name: 'Betrieb', exact: true })).toBeVisible()
  await page.locator('.enno-teaser').click()
  await expect(page.getByPlaceholder('Frag Enno …')).toBeVisible()

  await page.goto('/#/assistent')
  await page.reload()
  await expect(page.getByPlaceholder('Frag Enno …')).toBeVisible()
})

test('unbekannte Route fällt auf das Cockpit zurück, Logo führt zum Cockpit', async ({ page }) => {
  await page.goto('/#/gibt-es-nicht')
  await expect(page.locator('.content h1')).toHaveText('Cockpit')
  await page.goto('/#/backtest')
  await page.locator('.side-logo').click()
  await expect(page).toHaveURL(/#\/cockpit$/)
})

test('Hell/Dunkel schaltet um, bleibt nach Neuladen und Diagramme werden neu gezeichnet', async ({ page }) => {
  await page.goto('/#/cockpit')
  await settled(page)
  const before = await page.evaluate(() => document.documentElement.dataset.theme)
  await page.getByRole('button', { name: 'Hell/Dunkel umschalten' }).click()
  const after = await page.evaluate(() => document.documentElement.dataset.theme)
  expect(after).not.toBe(before)
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
  await expect(page.locator('.content canvas')).toHaveCount(1)
  await page.reload()
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe(after)
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(bg)
  await page.getByRole('button', { name: 'Hell/Dunkel umschalten' }).click()
})

test('Status-Anzeige zeigt den Stand aus /status', async ({ page }) => {
  const st = await api<{ latest_target_day: string; stale: boolean }>(page, '/status')
  await page.goto('/#/cockpit')
  const day = st.latest_target_day.split('-').reverse().join('.')
  await expect(page.locator('.topbar .pill')).toHaveText(st.stale ? `Daten vom ${day}` : `Fahrplan ${day}`)
})

test.describe('mobil (390 px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('Menü öffnet und schließt, kein horizontaler Überlauf auf allen Seiten', async ({ page }) => {
    await page.goto('/#/cockpit')
    const sidebar = page.locator('.sidebar')
    await page.getByRole('button', { name: 'Navigation öffnen' }).click()
    await expect(sidebar).toHaveClass(/open/)
    await page.getByRole('button', { name: 'Planung', exact: true }).click()
    await page.getByRole('link', { name: 'Risiko', exact: true }).click()
    await expect(sidebar).not.toHaveClass(/open/)
    await expect(page.locator('.content h1')).toHaveText('Risiko & Robustheit')

    const overflow: string[] = []
    for (const p of PAGES) {
      await page.goto(`/#/${p.path}`)
      await expect(page.locator('.content h1')).toHaveText(p.h1)
      await settled(page)
      const w = await page.evaluate(() => ({ doc: document.documentElement.scrollWidth, content: document.querySelector('.content')!.scrollWidth, vw: innerWidth }))
      if (w.doc > w.vw || w.content > w.vw) overflow.push(`${p.path}: ${w.content}px > ${w.vw}px`)
    }
    expect(overflow, 'Seiten mit horizontalem Überlauf').toEqual([])
  })
})
