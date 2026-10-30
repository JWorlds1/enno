// Speicher & MPC — Rolling Horizon trägt den Gasspeicher über Tagesgrenzen statt ihn jeden Tag zurückzusetzen.
import { useState } from 'react'
import { Bar, Line } from 'react-chartjs-2'
import { fldApi } from '@/lib/api'
import { Card, CardGrid, ChartBox, ErrorBanner, Note, PageShell, Section, Segmented, Skeleton, fmt, useApi } from '@/ui'

export function MpcPage() {
  const [days, setDays] = useState(14)
  const { data, error, loading } = useApi(() => fldApi.mpc(days), [days])

  const perDay = data && {
    labels: data.days.map((d) => d.slice(5)),
    datasets: [
      { label: 'Tagesisoliert', data: data.base_eur, backgroundColor: 'var(--c-price)' },
      { label: `MPC (Horizont ${data.horizon} Tage)`, data: data.mpc_eur, backgroundColor: 'var(--brand)' },
    ],
  }
  const levels = data && {
    labels: data.level_mpc.map((_, i) => (i % 96 === 0 ? data.days[i / 96].slice(5) : '')),
    datasets: [
      { label: 'Speicher MPC', data: data.level_mpc, borderColor: 'var(--brand-strong)', backgroundColor: 'var(--c-plasma-fill)', fill: true, pointRadius: 0 },
      { label: 'Speicher tagesisoliert', data: data.level_base, borderColor: 'var(--c-price)', borderWidth: 1, pointRadius: 0 },
      { label: 'Kapazität', data: data.level_mpc.map(() => data.s_max), borderColor: 'var(--fld-faint)', borderDash: [6, 4], pointRadius: 0 },
    ],
  }

  return (
    <PageShell title="Speicher & MPC" subtitle="Beide Varianten planen auf der Prognose und werden mit Ist-Preisen abgerechnet. Der Unterschied liegt nur im Horizont und darin, ob der Speicherstand über die Tagesgrenze getragen wird."
      actions={<Segmented value={days} onChange={setDays} options={[{ value: 7, label: '7 Tage' }, { value: 14, label: '14 Tage' }, { value: 30, label: '30 Tage' }]} />}>
      <ErrorBanner error={error} />
      <CardGrid>
        {loading || !data ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} />) : <>
          <Card label="Tagesisoliert" value={`${fmt(data.total_base)} €`} sub={`${data.days.length} Tage`} />
          <Card label="MPC" value={`${fmt(data.total_mpc)} €`} sub={`Horizont ${data.horizon} Tage`} />
          <Card label="Mehrwert" value={`${data.total_mpc >= data.total_base ? '+' : ''}${fmt(data.total_mpc - data.total_base)} €`} sub={`${fmt(data.uplift_per_mw_year)} € pro MW·a`} accent={data.total_mpc >= data.total_base ? 'green' : 'red'} />
          <Card label="Speicherkapazität" value={`${fmt(data.s_max, 1)} MWh`} sub="Gas, ≈ 1 Tag Budget" />
        </>}
      </CardGrid>

      <Section title="Speicherstand über die Tage">
        <ChartBox height={320}>{levels ? <Line data={levels} options={{ responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, scales: { x: { ticks: { autoSkip: false, maxRotation: 0 } }, y: { title: { display: true, text: 'MWh Gas' } } }, plugins: { legend: { position: 'bottom' } } }} /> : <Skeleton height="100%" />}</ChartBox>
      </Section>
      <Section title="Abgerechneter Tageserlös">
        <ChartBox height={260}>{perDay ? <Bar data={perDay} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }} /> : <Skeleton height="100%" />}</ChartBox>
      </Section>

      <Note title="Grenze">Der Mehrwert ist durch die Speichergröße gedeckelt, der Puffer reicht etwa einen Tag. Ein größerer Gasspeicher würde mehr Arbitrage über mehrere Tage zulassen.</Note>
    </PageShell>
  )
}
