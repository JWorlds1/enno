// EEG-Jahresbudget — Szenario § 39m: Marktprämie nur für 10 % der Leistung (≈ 876 Volllaststunden je MW und Jahr).
// Fährt die Anlage nur so viele Stunden: auf welchen Tagen? Auswahl nach dem vorab erwarteten Mehrerlös (Prognose),
// gezählt der tatsächlich erzielte — so, wie es im Betrieb entschieden worden wäre (Review H-06).
import { useEffect, useState } from 'react'
import { Line } from 'react-chartjs-2'
import { fldApi, type EegBudgetData } from '@/lib/api'
import { Card, Section, PageShell, ErrorBanner, fmt } from '@/ui'

export function EegPage() {
  const [d, setD] = useState<EegBudgetData | null>(null)
  const [annual, setAnnual] = useState(876)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fldApi.eegBudget(annual).then(setD).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [annual])

  const aff = d?.affordable_days ?? 0
  const chart = d ? {
    labels: d.cum_hours,
    datasets: [
      {
        label: `Im Budget (≤${annual} h)`,
        data: d.cum_value.map((v, i) => (i < aff ? v : null)),
        borderColor: 'var(--c-pos)', backgroundColor: 'var(--c-pos-fill)', fill: true, pointRadius: 0, tension: 0.1,
      },
      {
        label: 'Über Budget (theoretisch)',
        data: d.cum_value.map((v, i) => (i >= aff - 1 ? v : null)),
        borderColor: 'var(--fld-faint)', borderDash: [5, 3], backgroundColor: 'transparent', pointRadius: 0, tension: 0.1,
      },
    ],
  } : null

  return (
    <PageShell title="EEG-Jahresbudget" subtitle="Biomethan nach § 39m EEG: Marktprämie nur für 10 % der Leistung, also rund 876 Volllaststunden je MW. Wenn die Anlage nur so viele Stunden fährt — auf welchen Tagen?">
      <ErrorBanner error={error} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 22 }}>
        <Card label="Jahres-Volllaststunden" value={`${annual} h`} sub="Prämienmenge § 39m (Szenario)" accent="blue" />
        <Card label="Leistbare Betriebstage" value={`${fmt(d?.affordable_days)}`} sub={`bei ${d?.daily_hours ?? 8} h/Tag`} />
        <Card label="Mehrerlös im Budget" value={`${fmt(d?.value_at_budget)} €`} sub={d?.ranking === 'nachtraeglich' ? 'Tage nachträglich sortiert (alter Backtest)' : 'Tage nach Prognose gewählt'} accent="green" />
        <Card label="Anteil am Potenzial" value={`${fmt(d?.pct_of_max)} %`} sub={`von ${fmt(d?.total_days)} Tagen (Backtest)`} accent="amber" />
      </div>

      <Section title="Kumulativer Mehrerlös nach Volllaststunden (Tage nach erwartetem Mehrerlös sortiert)">
        <div style={{ height: 360 }}>
          {chart ? <Line data={chart} options={{ responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { position: 'bottom' } }, scales: { x: { title: { display: true, text: 'kumulierte Volllaststunden' }, ticks: { maxTicksLimit: 12 } }, y: { title: { display: true, text: '€ kumuliert' } } } }} />
            : <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--fld-faint)' }}>lädt…</div>}
        </div>
        {d && (
          <div style={{ marginTop: 10, fontSize: 13, color: 'var(--fld-muted)' }}>
            → Mit <b>{annual} h/Jahr</b> (≈ {d.affordable_days} beste Betriebstage) fängst du <b>{fmt(d.pct_of_max)}%</b> des Mehrerlöses, den {d.daily_hours} h an jedem der {d.total_days} Backtest-Tage brächten. Die Tage sind so gewählt, wie es im Betrieb ginge: nach dem Mehrerlös, den die Prognose am Vortag erwarten ließ.
            <br />Einordnung: § 39m begrenzt die <b>Prämie</b>, nicht den Betrieb. Cockpit und Backtest rechnen mit {d.daily_hours} h an jedem Tag; diese Seite zeigt den Fall, dass sich der Betrieb außerhalb der Prämienmenge nicht lohnt. Welche Lesart für die FLD-Anlage gilt, legt FLD fest.
          </div>
        )}
        <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13, color: 'var(--fld-muted)' }}>Jahresbudget:</span>
          {[657, 876, 1095].map((h) => (
            <button key={h} onClick={() => setAnnual(h)} style={{ padding: '6px 12px', borderRadius: 8, fontSize: 13, cursor: 'pointer', border: `1px solid ${annual === h ? 'var(--brand)' : 'var(--fld-border)'}`, background: annual === h ? 'var(--brand-soft)' : 'var(--fld-card)', color: annual === h ? 'var(--fld-text)' : 'var(--fld-muted)' }}>{h} h</button>
          ))}
        </div>
      </Section>
    </PageShell>
  )
}
