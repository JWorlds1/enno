// Erlös-Stapel — Energie (Spot/Wärme/PtX) + Regelenergie-Kapazität gegenüber reinem Spotbetrieb.
import { useState } from 'react'
import { Bar } from 'react-chartjs-2'
import { fldApi } from '@/lib/api'
import { Card, CardGrid, ChartBox, ErrorBanner, Note, PageShell, Section, Segmented, Skeleton, fmt, signed, useApi } from '@/ui'

export function RevenueStackPage() {
  const [days, setDays] = useState(7)
  const { data, error, loading } = useApi(() => fldApi.revenueStack(days), [days])

  const chart = data && {
    labels: data.rows.map((r) => r.day.slice(5)),
    datasets: [
      { type: 'bar' as const, label: 'Energie (Spot, Wärme, PtX)', data: data.rows.map((r) => r.energy), backgroundColor: 'var(--c-price)', stack: 'co' },
      { type: 'bar' as const, label: 'Regelenergie-Kapazität', data: data.rows.map((r) => r.capacity), backgroundColor: 'var(--brand)', stack: 'co' },
      { type: 'line' as const, label: 'Nur Spot (Referenz)', data: data.rows.map((r) => r.spot_only), borderColor: 'var(--c-neg)', backgroundColor: 'var(--c-neg)', borderDash: [5, 4], pointRadius: 3 },
    ],
  }

  return (
    <PageShell title="Erlös-Stapel" subtitle="Co-Optimierung: Jedes MW wird dorthin vergeben, wo es am meisten bringt, also an den Spotmarkt oder als aFRR-/FCR-Vorhaltung in 4-h-Blöcken."
      actions={<Segmented value={days} onChange={setDays} options={[{ value: 7, label: '7 Tage' }, { value: 14, label: '14 Tage' }]} />}>
      <ErrorBanner error={error} />
      <CardGrid>
        {loading || !data ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} />) : <>
          <Card label="Ø Mehrerlös / Tag" value={`${signed(data.avg_uplift)} €`} sub="Co-Opt vs. nur Spot" accent="green" />
          <Card label="Hochgerechnet" value={`${fmt(data.uplift_per_mw_year)} €`} sub="pro MW und Jahr" accent="amber" />
          <Card label="aFRR Ø" value={`${fmt(data.afrr, 1)} €/MW·h`} sub="Kapazitätspreis" />
          <Card label="FCR Ø" value={`${fmt(data.fcr, 1)} €/MW·h`} sub="Kapazitätspreis" />
        </>}
      </CardGrid>

      <Section title="Tageserlös nach Quelle">
        <ChartBox height={360}>
          {chart ? <Bar data={chart as never} options={{
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: '€ / Tag' } } },
            plugins: { legend: { position: 'bottom' } },
          }} /> : <Skeleton height="100%" />}
        </ChartBox>
      </Section>

      {data && <Section title="Je Tag">
        <table>
          <thead><tr><th>Tag</th><th>Nur Spot €</th><th>Energie €</th><th>Kapazität €</th><th>Co-Opt €</th><th>Mehrerlös €</th><th>Ø Reserve MW</th></tr></thead>
          <tbody>{data.rows.map((r) => (
            <tr key={r.day}><td>{r.day}</td><td>{fmt(r.spot_only)}</td><td>{fmt(r.energy)}</td><td>{fmt(r.capacity)}</td><td>{fmt(r.coopt)}</td>
              <td style={{ color: 'var(--c-pos)', fontWeight: 600 }}>{signed(r.uplift)}</td><td>{fmt(r.reserve_mw, 2)}</td></tr>
          ))}</tbody>
        </table>
      </Section>}

      <Note title="Grenze">Die Kapazitätspreise sind Mittelwerte der beobachteten Auktionen. Zuschlagsrisiko und Abrufenergie sind nicht modelliert, der Wert ist also eine Obergrenze.</Note>
    </PageShell>
  )
}
