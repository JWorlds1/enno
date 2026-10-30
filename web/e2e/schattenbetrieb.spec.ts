// Schattenbetrieb: Seite zeigt den Stand aus /shadow; kaputte Messdatei → verständliche Ablehnung, nichts gespeichert.
import { api, expect, kpi, settled, test } from './fixtures'

test('Schattenbetrieb: Kennzahlen aus /shadow, kaputte Datei wird abgelehnt', async ({ page, guard }) => {
  guard.allowApiErrors(/measurements/)
  guard.allowApiErrors(/422 \(Unprocessable/)
  const before = await api<{ summary: { days: number }; measurements: number }>(page, '/shadow')
  await page.goto('/#/schattenbetrieb')
  await settled(page)
  await expect(kpi(page, 'Verglichene Tage')).toHaveText(String(before.summary.days))
  await page.locator('input[type=file]').setInputFiles({ name: 'kaputt.csv', mimeType: 'text/csv', buffer: Buffer.from('nur eine spalte') })
  await expect(page.getByRole('alert')).toContainText('keine Zeile „zeit;leistung“ erkannt')
  const after = await api<{ measurements: number }>(page, '/shadow')
  expect(after.measurements).toBe(before.measurements)
})
