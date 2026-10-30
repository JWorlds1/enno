// CDR-Preis-Sensitivität (MA-Winkel): ab welchem CDR-Kohlenstoffpreis schlägt Plasma-Pyrolyse
// die Elektrolyse? Sweep €80→240/t, Netto Plasma vs. Elektrolyse + Break-Even + Carbon/Pyro.
import { useEffect, useState } from 'react'
import { Line } from 'react-chartjs-2'
import { fldApi, marketGas, type CdrData } from '@/lib/api'
import { Card, Section, PageShell, ErrorBanner, fmt } from '@/ui'

export function CdrPage() {
  const [d, setD] = useState<CdrData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [gas, setGas] = useState<number | null>(null)
  const [eua, setEua] = useState<number | null>(null)

  // Gas wie überall: Biomethan heute (TTF + Aufschlag), EUA = letzter Marktwert — keine festen Annahmen (Review N-05)
  useEffect(() => {
    marketGas().catch(() => null).then((m) => {
      const g = m?.gas ?? 70
      setGas(g)
      return fldApi.cdrSensitivity(g)
    }).then(setD).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
    fldApi.market().then((mk) => setEua([...mk].sort((a, b) => b.day.localeCompare(a.day)).find((x) => x.eua_co2_eur_t != null)?.eua_co2_eur_t ?? null)).catch(() => {})
  }, [])

  const rows = d?.rows ?? []
  const labels = rows.map((r) => `${r.co2}`)
  const netChart = {
    labels,
    datasets: [
      { label: 'Netto Plasma-Pyrolyse €', data: rows.map((r) => r.plasma_net), borderColor: 'var(--c-pos)', backgroundColor: 'transparent', pointRadius: 2, tension: 0.2 },
      { label: 'Netto Elektrolyse €', data: rows.map((r) => r.electro_net), borderColor: 'var(--c-elektro)', borderDash: [5, 3], backgroundColor: 'transparent', pointRadius: 2, tension: 0.2 },
    ],
  }
  const carbonChart = {
    labels,
    datasets: [
      { label: 'Kohlenstoff t (Plasma)', data: rows.map((r) => r.plasma_carbon_t), borderColor: 'var(--c-plasma)', backgroundColor: 'var(--c-plasma-fill)', yAxisID: 'yc', fill: true, pointRadius: 0, tension: 0.2 },
      { label: 'H₂ MWh (Plasma)', data: rows.map((r) => r.plasma_h2_mwh), borderColor: 'var(--c-h2)', backgroundColor: 'transparent', yAxisID: 'yh', pointRadius: 0, tension: 0.2 },
    ],
  }

  const be = d?.break_even_co2
  const maxUplift = rows.length ? Math.max(...rows.map((r) => r.plasma_uplift)) : null

  return (
    <PageShell title="CDR-Preis-Sensitivität" subtitle="Ab welchem CDR-Kohlenstoffpreis lohnt sich Plasma-Pyrolyse gegenüber Elektrolyse? (Sweep über den aktuellen Fahrplan)">
      <ErrorBanner error={error} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 22 }}>
        <Card label="Break-Even CDR-Preis" value={be != null ? `${be} €/t` : 'kein Wechsel'} sub="ab hier schlägt Plasma Elektrolyse" accent={be != null ? 'green' : 'amber'} />
        <Card label="Max. Mehrerlös (Plasma)" value={`${fmt(maxUplift)} €`} sub="über den CDR-Bereich" accent="green" />
        <Card label="EUA-Referenz" value={eua != null ? `${fmt(eua)} €/t` : '—'} sub={`Emissionspreis heute · Gas ${fmt(gas)} €/MWh`} accent="blue" />
        <Card label="Voluntary-CDR-Markt" value="125–250 €/t" sub="Biochar/CDR (Puro etc.)" accent="amber" />
      </div>

      <Section title="Netto-Erlös: Plasma-Pyrolyse vs. Elektrolyse über den CDR-Preis">
        <div style={{ height: 340 }}>
          {rows.length ? <Line data={netChart} options={{ responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { position: 'bottom' } }, scales: { x: { title: { display: true, text: 'CDR-Preis €/t' } }, y: { title: { display: true, text: 'Netto €' } } } }} />
            : <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--fld-faint)' }}>rechnet Sweep…</div>}
        </div>
        {be != null && (
          <div style={{ marginTop: 10, fontSize: 13, color: 'var(--fld-muted)' }}>
            → Ab <b>{be} €/t</b> CDR-Preis ist die Plasma-Pyrolyse-Route netto besser als reine Elektrolyse. Da der Voluntary-CDR-Markt (125–250 €/t) deutlich über dem EUA-Preis ({fmt(eua)} €/t) liegt, lohnt sich die Pyrolyse-Vermarktung als CDR-Produkt.
          </div>
        )}
      </Section>

      <Section title="Kohlenstoff- & H₂-Ausbeute steigt mit dem CDR-Preis">
        <div style={{ height: 300 }}>
          {rows.length ? <Line data={carbonChart} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { title: { display: true, text: 'CDR-Preis €/t' } }, yc: { position: 'left', title: { display: true, text: 't Kohlenstoff' } }, yh: { position: 'right', title: { display: true, text: 'MWh H₂' }, grid: { drawOnChartArea: false } } } }} />
            : <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--fld-faint)' }}>rechnet…</div>}
        </div>
      </Section>
    </PageShell>
  )
}
