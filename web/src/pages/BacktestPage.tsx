// Nachweis / Backtest — Fahrplan am Vortag auf der Prognose geplant, zu Ist-Preisen abgerechnet, gegen Dauerbetrieb.
import { useEffect, useState } from 'react'
import { Line } from 'react-chartjs-2'
import { fldApi, type BacktestPoint } from '@/lib/api'
import { Card, Section, PageShell, ErrorBanner, fmt } from '@/ui'

export function BacktestPage() {
  const [bt, setBt] = useState<BacktestPoint[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fldApi.backtest().then(setBt).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const sumFc = bt.reduce((a, x) => a + (x.up_fc ?? 0), 0)
  const sumPf = bt.reduce((a, x) => a + (x.up_pf ?? 0), 0)
  const capture = sumPf > 0 ? (sumFc / sumPf) * 100 : null
  const betterDays = bt.filter((x) => (x.up_fc ?? 0) >= -0.5).length  // Mehrerlös ≥ 0 (nicht Löserstatus)
  const span = bt.length ? `${new Date(bt[0].day).toLocaleDateString('de-DE')} – ${new Date(bt[bt.length - 1].day).toLocaleDateString('de-DE')}` : ''

  let cFc = 0, cPf = 0
  const cumFc: number[] = [], cumPf: number[] = []
  for (const x of bt) { cFc += x.up_fc ?? 0; cPf += x.up_pf ?? 0; cumFc.push(cFc); cumPf.push(cPf) }

  const chart = {
    labels: bt.map((x) => x.day),
    datasets: [
      { label: 'Kumulativer Mehrerlös (Prognose)', data: cumFc, borderColor: 'var(--c-pos)', backgroundColor: 'var(--c-pos-fill)', fill: true, pointRadius: 0, tension: 0.15 },
      { label: 'Obergrenze (perfekte Voraussicht)', data: cumPf, borderColor: 'var(--fld-faint)', borderDash: [6, 4], backgroundColor: 'transparent', pointRadius: 0, tension: 0.15 },
    ],
  }

  return (
    <PageShell title="Nachweis / Backtest" subtitle={`${bt.length} echte Tage (${span}): Fahrplan jeweils am Vortag auf der Prognose geplant, zu den tatsächlichen Preisen abgerechnet — gegen Dauerbetrieb.`}>
      <ErrorBanner error={error} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 22 }}>
        <Card label="Getestete Tage" value={fmt(bt.length)} sub={`an ${betterDays} mindestens so gut wie Dauerbetrieb`} />
        <Card label="Mehrerlös gesamt" value={`${fmt(sumFc)} €`} sub="über alle Tage" accent="green" />
        <Card label="Ø Mehrerlös / Tag" value={`${fmt(bt.length ? sumFc / bt.length : null)} €`} accent="green" />
        <Card label="Treffsicherheit" value={capture != null ? `${fmt(capture)} %` : '—'} sub="vom Mehrerlös mit perfekter Voraussicht" accent="blue" />
      </div>
      <Section title={`Kumulativer Mehrerlös über ${bt.length} Tage`}>
        <div style={{ height: 380 }}>
          {bt.length ? <Line data={chart} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { ticks: { maxTicksLimit: 12 } }, y: { title: { display: true, text: '€ kumuliert' } } } }} />
            : <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--fld-faint)' }}>lädt…</div>}
        </div>
      </Section>
    </PageShell>
  )
}
