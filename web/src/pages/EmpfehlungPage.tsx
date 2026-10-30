// Fahrplan für den Liefertag + Begründung des Entscheidungs-Agenten (Rationale/Guardrails).
import { useEffect, useState } from 'react'
import { fldApi, type Recommendation, type DecisionOut } from '@/lib/api'
import { Card, Section, PageShell, ErrorBanner, fmt, marketTime, signed, starts } from '@/ui'

const GUARD: Record<string, string> = {
  heat_min_runtime: 'Wärme-Mindestlauf', solver_feasible: 'Fahrplan lösbar', capacity_ok: 'Leistungsgrenze', ptx_consistent: 'Elektrolyse plausibel',
}

export function EmpfehlungPage() {
  const [rec, setRec] = useState<Recommendation | null>(null)
  const [dec, setDec] = useState<DecisionOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.allSettled([fldApi.recommendation(), fldApi.decision()]).then(([r, d]) => {
      if (r.status === 'fulfilled') setRec(r.value)
      else setError(r.reason instanceof Error ? r.reason.message : String(r.reason))
      if (d.status === 'fulfilled') setDec(d.value)
    })
  }, [])

  const k = rec?.kpis ?? {}
  const slots = rec?.slots ?? []
  // stündlich verdichten nach Marktzeit aus den Zeitstempeln: 24 Zeilen, am 29.03. 23, am 25.10. 25 (02:00 doppelt)
  const groups: (typeof slots)[] = []
  slots.forEach((s, i) => {
    const label = s.ts ? marketTime(s.ts, false).slice(0, 2) : String(Math.floor(i / 4)).padStart(2, '0')
    const last = groups.at(-1)
    const prev = last?.at(-1)
    const prevLabel = prev ? (prev.ts ? marketTime(prev.ts, false).slice(0, 2) : String(Math.floor((i - 1) / 4)).padStart(2, '0')) : null
    if (last && prevLabel === label && last.length < 4) last.push(s)
    else groups.push([s])
  })
  const hours = groups.map((seg, i) => {
    const avg = (f: (s: typeof slots[number]) => number | null | undefined) => seg.reduce((a, s) => a + (f(s) ?? 0), 0) / seg.length
    const h = seg[0].ts ? marketTime(seg[0].ts, false) : `${String(i).padStart(2, '0')}:00`
    return { key: `${i}-${h}`, h, price: avg((s) => s.pred_price), bhkw: avg((s) => s.bhkw_mw), el: avg((s) => s.electrolyser_mw),
      up: avg((s) => s.reserve_up_mw), down: avg((s) => s.reserve_down_mw) }
  })
  const reserve = slots.some((s) => (s.reserve_up_mw ?? 0) + (s.reserve_down_mw ?? 0) > 0)
  const day = rec ? new Date(`${rec.target_day}T12:00:00Z`).toLocaleDateString('de-DE', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Berlin' }) : 'morgen'

  return (
    <PageShell title="Fahrplan" subtitle={`Für ${day} — was die Anlage tun soll und warum.`}
      actions={<a className="btn" href="/fld-api/recommendation.csv" download>Fahrplan herunterladen (CSV)</a>}>
      <ErrorBanner error={error} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 22 }}>
        <Card label="Erwarteter Erlös" value={`${fmt(k['expected_revenue_eur'])} €`} accent="green" />
        <Card label="Mehrerlös" value={`${signed(k['expected_uplift_eur'])} €`} accent="green" />
        <Card label="BHKW-Laufzeit" value={`${fmt(k['bhkw_runtime_h'], 1)} h`} sub={starts(k['bhkw_starts'])} />
        <Card label="Strategie" value={dec?.label ?? dec?.strategy ?? '—'} accent="amber" />
      </div>

      <Section title="Warum diese Strategie (Entscheidungs-Agent)">
        {dec?.rationale?.length ? (
          <ul style={{ margin: 0, paddingLeft: 18, color: 'var(--fld-text)', fontSize: 14, lineHeight: 1.7 }}>
            {dec.rationale.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        ) : <div style={{ color: 'var(--fld-faint)', fontSize: 14 }}>keine Begründung hinterlegt</div>}
        {dec?.guardrails && (
          <div style={{ marginTop: 14, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {Object.entries(dec.guardrails).map(([key, val]) => {
              const ok = val === 'ok'  // Werte sind Texte ("ok" | "VERLETZT" | "pruefen") — jeder nicht leere Text wäre truthy
              return (
                <span key={key} style={{ fontSize: 12, padding: '4px 10px', borderRadius: 999, background: ok ? 'var(--pos-bg)' : 'var(--neg-bg)', color: ok ? 'var(--pos-ink)' : 'var(--neg-ink)' }}>
                  {ok ? '✓' : '✗'} {GUARD[key] ?? key}{ok ? '' : ` — ${String(val)}`}
                </span>
              )
            })}
          </div>
        )}
      </Section>

      <Section title="Stundenfahrplan">
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead><tr style={{ textAlign: 'left', color: 'var(--fld-muted)', borderBottom: '1px solid var(--fld-border)' }}>
              <th style={{ padding: '7px 10px' }}>Stunde</th><th style={{ padding: '7px 10px' }}>Ø Preis €/MWh</th>
              <th style={{ padding: '7px 10px' }}>BHKW MW</th><th style={{ padding: '7px 10px' }}>Elektrolyse MW</th>
              {reserve && <><th style={{ padding: '7px 10px' }}>Reserve ↑ MW</th><th style={{ padding: '7px 10px' }}>Reserve ↓ MW</th></>}
              <th style={{ padding: '7px 10px' }}>Aktion</th>
            </tr></thead>
            <tbody>
              {hours.map((r) => (
                <tr key={r.key} style={{ borderBottom: '1px solid var(--fld-soft)' }}>
                  <td style={{ padding: '7px 10px' }}>{r.h}</td>
                  <td style={{ padding: '7px 10px' }}>{fmt(r.price, 1)}</td>
                  <td style={{ padding: '7px 10px', color: r.bhkw > 0.01 ? 'var(--c-pos)' : 'var(--fld-faint)', fontWeight: r.bhkw > 0.01 ? 600 : 400 }}>{fmt(r.bhkw, 2)}</td>
                  <td style={{ padding: '7px 10px', color: r.el > 0.01 ? 'var(--c-elektro)' : 'var(--fld-faint)' }}>{fmt(r.el, 2)}</td>
                  {reserve && <><td style={{ padding: '7px 10px' }}>{fmt(r.up, 2)}</td><td style={{ padding: '7px 10px' }}>{fmt(r.down, 2)}</td></>}
                  <td style={{ padding: '7px 10px' }}>{r.bhkw > 0.01 ? '⚡ Strom verkaufen' : r.el > 0.01 ? '💧 H₂ / Bezug' : '⏸ pausieren'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </PageShell>
  )
}
