// Vorwärmen wie im Betrieb (FLD_WARMUP): die sechs MILP-Analysen und die Splitter-Jahresrechnung (~32 s kalt bei
// Load 17, 22.10.) einmal über die echte API rechnen.
// Ohne das zahlt der erste Test die Kaltrechnung (/risk allein ~31 s auf dem Intel-MacBook) und
// reißt unter Last das 45-s-Limit. Pfade = Aufrufe der Seiten (web/src/lib/api.ts), also derselbe Cache-Schlüssel.
const HEAVY = ['/risk', '/pareto', '/revenue-stack?days=7', '/plasma-compare?days=10', '/forecast-band?days=7', '/mpc?days=14',
  '/splitter-year?carbon=co2']

export default async function globalSetup() {
  const port = process.env.FLD_E2E_BACKEND_PORT ?? '8031'
  for (const p of HEAVY) {
    const r = await fetch(`http://127.0.0.1:${port}/api/v1${p}`, { signal: AbortSignal.timeout(300_000) })
    if (!r.ok) throw new Error(`Vorwärmen ${p} → ${r.status}`)
  }
}
