// Prognose-Güte — Ist vs. Prognose, P10/P90-Unsicherheitsband, MAE/Abdeckung.
import { useEffect, useState } from 'react'
import { Line } from 'react-chartjs-2'
import { fldApi, modelApi, type ForecastPoint } from '@/lib/api'
import { Card, Section, PageShell, ErrorBanner, fmt, marketTime, useApi } from '@/ui'

export function ForecastPage() {
  const [fc, setFc] = useState<ForecastPoint[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fldApi.forecast().then(setFc).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const { data: mq } = useApi(() => modelApi.get(), [])  // Güte über 12 Monate statt eines einzelnen Tages

  const labels = fc.map((p) => marketTime(p.ts))
  const chart = {
    labels,
    datasets: [
      { label: 'P90', data: fc.map((p) => p.p90), borderColor: 'transparent', backgroundColor: 'var(--c-elektro-fill)', fill: '+1', pointRadius: 0 },
      { label: 'P10', data: fc.map((p) => p.p10), borderColor: 'transparent', backgroundColor: 'transparent', fill: false, pointRadius: 0 },
      { label: 'Ist', data: fc.map((p) => p.actual), borderColor: 'var(--fld-text)', backgroundColor: 'transparent', pointRadius: 0, tension: 0.2, borderWidth: 2 },
      { label: 'Prognose (genutzt)', data: fc.map((p) => p.pred_b), borderColor: 'var(--c-neg)', backgroundColor: 'transparent', pointRadius: 0, tension: 0.2, borderDash: [5, 3] },
    ],
  }

  return (
    <PageShell title="Prognose-Güte" subtitle="Wie gut trifft die Preisprognose — und wie ehrlich ist die Unsicherheit (P10–P90)?">
      <ErrorBanner error={error} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 22 }}>
        <Card label="Prognosefehler (MAE)" value={mq ? `${fmt(mq.mae_eur_mwh, 1)} €/MWh` : '—'} sub={mq ? `${mq.days} Tage rollierend · „wie gestern“: ${fmt(mq.mae_naive_eur_mwh, 1)}` : 'Tageskette noch nicht gelaufen'} />
        <Card label="P10–P90 Abdeckung" value={mq ? `${fmt(mq.coverage_p10_p90 * 100)} %` : '—'} sub="Ziel ≈ 80 %, 12 Monate" accent={mq && mq.coverage_p10_p90 >= 0.7 ? 'green' : 'amber'} />
        <Card label="Punkte" value={fmt(fc.length)} sub="letzte 96 Slots" />
      </div>
      <Section title="Ist vs. Prognose mit Unsicherheitsband">
        <div style={{ height: 400 }}>
          {fc.length ? <Line data={chart} options={{ responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { position: 'bottom' } }, scales: { x: { ticks: { maxTicksLimit: 10 } }, y: { title: { display: true, text: '€/MWh' } } } }} />
            : <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--fld-faint)' }}>lädt…</div>}
        </div>
      </Section>
    </PageShell>
  )
}
