// Prognoseband — roh (Quantil-LGBM) vs. CQR (statisch) vs. ACI (adaptiv) mit realisierter Abdeckung.
import { useState } from 'react'
import { Line } from 'react-chartjs-2'
import { fldApi } from '@/lib/api'
import { Card, CardGrid, ChartBox, ErrorBanner, Note, PageShell, Section, Segmented, Skeleton, fmt, useApi, marketTime } from '@/ui'

const pct = (v: number) => `${fmt(v * 100)} %`

export function ForecastBandPage() {
  const [days, setDays] = useState(7)
  const { data, error, loading } = useApi(() => fldApi.forecastBand(days), [days])
  const s = data?.series ?? []
  const labels = s.map((p) => marketTime(p.ts))

  const band = {
    labels,
    datasets: [
      { label: 'ACI-Band (Ziel 80 %)', data: s.map((p) => p.aci_hi), borderColor: 'transparent', backgroundColor: 'var(--c-plasma-fill)', fill: '+1', pointRadius: 0 },
      { label: 'ACI-Band unten', data: s.map((p) => p.aci_lo), borderColor: 'transparent', pointRadius: 0 },
      { label: 'Roh P10–P90', data: s.map((p) => p.raw_hi), borderColor: 'var(--c-elektro)', borderDash: [3, 3], borderWidth: 1, pointRadius: 0 },
      { label: 'Roh P10–P90 unten', data: s.map((p) => p.raw_lo), borderColor: 'var(--c-elektro)', borderDash: [3, 3], borderWidth: 1, pointRadius: 0 },
      { label: 'Ist-Preis', data: s.map((p) => p.actual), borderColor: 'var(--c-price)', borderWidth: 1.5, pointRadius: 0 },
    ],
  }
  const cov = {
    labels,
    datasets: [
      { label: 'ACI-Abdeckung (gleitend 24 h)', data: s.map((p) => p.aci_cov_24h * 100), borderColor: 'var(--brand-strong)', pointRadius: 0 },
      { label: 'Ziel', data: s.map(() => (data?.target ?? 0.8) * 100), borderColor: 'var(--fld-faint)', borderDash: [6, 4], pointRadius: 0 },
    ],
  }
  const opts = (y: string) => ({
    responsive: true, maintainAspectRatio: false, interaction: { mode: 'index' as const, intersect: false },
    scales: { x: { ticks: { maxTicksLimit: 10 } }, y: { title: { display: true, text: y } } },
    plugins: { legend: { position: 'bottom' as const, labels: { filter: (i: { text: string }) => !i.text.endsWith('unten') } } },
  })

  return (
    <PageShell title="Prognoseband" subtitle="Wie ehrlich ist die Unsicherheit? Ein 80-%-Band sollte 80 % der Ist-Preise enthalten. Konforme Verfahren reparieren die Unterdeckung der Rohquantile."
      actions={<Segmented value={days} onChange={setDays} options={[{ value: 3, label: '3 Tage' }, { value: 7, label: '7 Tage' }, { value: 14, label: '14 Tage' }]} />}>
      <ErrorBanner error={error} />
      <CardGrid>
        {loading || !data ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} />) : <>
          <Card label="Ziel-Abdeckung" value={pct(data.target)} sub={`${data.test_n} Testslots`} />
          <Card label="Roh (Quantile)" value={pct(data.coverage.raw)} sub={`Ø Breite ${fmt(data.width.raw)} €/MWh`} accent="red" />
          <Card label="CQR (statisch)" value={pct(data.coverage.cqr)} sub={`Ø Breite ${fmt(data.width.cqr)} €/MWh`} accent="amber" />
          <Card label="ACI (adaptiv)" value={pct(data.coverage.aci)} sub={`Ø Breite ${fmt(data.width.aci)} €/MWh`} accent="green" />
        </>}
      </CardGrid>

      <Section title="Ist-Preis im Prognoseband">
        <ChartBox height={380}>{s.length ? <Line data={band} options={opts('€/MWh')} /> : <Skeleton height="100%" />}</ChartBox>
      </Section>
      <Section title="Realisierte Abdeckung">
        <ChartBox height={220}>{s.length ? <Line data={cov} options={opts('%')} /> : <Skeleton height="100%" />}</ChartBox>
      </Section>

      <Note title="Einordnung">
        Statisches CQR setzt Austauschbarkeit voraus. Die bricht bei einem Regimewechsel des Marktes, und das Band bleibt zu schmal.
        ACI passt die Breite online an die beobachtete Abdeckung an und erreicht das Ziel, dafür wird das Band breiter.
      </Note>
    </PageShell>
  )
}
