// Gemeinsames Fixture: jeder Test scheitert bei Konsolenfehlern oder API-Antworten ≥ 400,
// außer er erlaubt sie ausdrücklich (allowApiErrors). So bleibt kein stiller Fehler unentdeckt.
import { test as base, expect, type Page, type Response } from '@playwright/test'

interface Guard {
  allowApiErrors: (pattern: RegExp) => void
  apiCalls: { method: string; url: string; status: number; body: string | null }[]
}

export const test = base.extend<{ guard: Guard }>({
  guard: [async ({ page }, use) => {
    const consoleErrors: string[] = []
    const apiErrors: string[] = []
    const allowed: RegExp[] = []
    const apiCalls: Guard['apiCalls'] = []
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
    page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`))
    page.on('response', (r) => {
      const url = r.url()
      if (!url.includes('/fld-api/')) return
      const req = r.request()
      apiCalls.push({ method: req.method(), url, status: r.status(), body: req.postData() })
      if (r.status() >= 400 && !allowed.some((p) => p.test(url))) apiErrors.push(`${req.method()} ${url} → ${r.status()}`)
    })
    await use({ allowApiErrors: (p) => allowed.push(p), apiCalls })
    const relevant = consoleErrors.filter((t) => !allowed.some((p) => p.test(t)))
    expect(apiErrors, 'API-Fehler im Test').toEqual([])
    expect(relevant, 'Konsolenfehler im Browser').toEqual([])
  }, { auto: true }],
})
export { expect }

/** Zahl so formatieren wie die App (de-DE, ohne Nachkommastellen falls nicht angegeben). */
export const de = (v: number, dp = 0) => v.toLocaleString('de-DE', { maximumFractionDigits: dp })

/** Wartet, bis keine Lade-Platzhalter mehr im Inhalt stehen. */
export async function settled(page: Page) {
  await expect(page.locator('.content .skeleton')).toHaveCount(0)
}

/** API direkt abfragen (dieselbe Quelle, aus der die UI liest) — Grundlage für den Vergleich UI ↔ Backend. */
export async function api<T>(page: Page, path: string): Promise<T> {
  const r = await page.request.get(`/fld-api${path}`)
  expect(r.status(), `GET ${path}`).toBe(200)
  return r.json() as Promise<T>
}

/** Karte (KPI) per Label finden und ihren Wert lesen. */
export function kpi(page: Page, label: string) {
  return page.locator('.kpi', { has: page.locator('.kpi-label', { hasText: label }) }).locator('.kpi-value')
}

/** Startwert Gas wie die Seite: TTF (letzter Markttag) + Biomethan-Aufschlag der Anlage. */
export async function gasStart(page: Page) {
  const mk = await api<{ day: string; ttf_gas_eur_mwh: number | null }[]>(page, '/market')
  const cfg = await api<{ defaults: Record<string, number>; override: Record<string, number> }>(page, '/plant-config')
  const ttf = [...mk].sort((a, b) => b.day.localeCompare(a.day)).find((x) => x.ttf_gas_eur_mwh != null)!.ttf_gas_eur_mwh!
  return Math.round(ttf + (cfg.override.bio_premium_eur_mwh ?? cfg.defaults.bio_premium_eur_mwh))
}
export const whatif = (pred: (b: Record<string, unknown>) => boolean) => (r: Response) =>
  r.url().endsWith('/fld-api/whatif') && pred(r.request().postDataJSON())
