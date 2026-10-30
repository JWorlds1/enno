// Pareto — Erlös gegen CO₂-Einsparung: Lohnt eigene Vermeidung oder ist das Zertifikat billiger?
import { Scatter } from 'react-chartjs-2'
import { fldApi } from '@/lib/api'
import { Card, CardGrid, ChartBox, ErrorBanner, Note, PageShell, Section, Skeleton, fmt, useApi } from '@/ui'

export function ParetoPage() {
  const { data, error, loading } = useApi(fldApi.pareto)

  const chart = data && {
    datasets: [{
      label: 'Pareto-Front',
      data: data.front.map((p) => ({ x: p.co2_t, y: p.profit })),
      borderColor: 'var(--c-pos)', backgroundColor: 'var(--c-pos)', showLine: true, pointRadius: 5,
    }],
  }

  return (
    <PageShell title="Erlös ↔ CO₂" subtitle="ε-constraint-Optimierung: Der Fahrplan wird schrittweise gezwungen, mehr Netz-CO₂ zu verdrängen. Die Steigung der Front sind die Vermeidungskosten je Tonne.">
      <ErrorBanner error={error} />
      <CardGrid>
        {loading || !data ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} />) : <>
          <Card label="Vermeidungskosten" value={data.slope_eur_t != null ? `${fmt(data.slope_eur_t)} €/t` : '—'} sub="Erlösverzicht je zusätzlicher t CO₂" accent={data.cheaper_than_eua ? 'green' : 'red'} />
          <Card label="EUA-Preis" value={`${fmt(data.eua)} €/t`} sub="Vergleichsmaßstab" />
          <Card label="Gaskosten" value={`${fmt(data.gas_cost)} €/MWh`} sub="TTF + Biomethan-Aufschlag" />
          <Card label="Analysetag" value={data.day} sub={`${data.front.length} Stützpunkte`} />
        </>}
      </CardGrid>

      <Section title="Pareto-Front">
        <ChartBox>
          {chart ? <Scatter data={chart} options={{
            responsive: true, maintainAspectRatio: false,
            scales: { x: { title: { display: true, text: 'Verdrängtes Netz-CO₂ (t/Tag)' } }, y: { title: { display: true, text: 'Tageserlös (€)' } } },
          }} /> : <Skeleton height="100%" />}
        </ChartBox>
      </Section>

      {data && data.slope_eur_t != null && (
        <Note tone={data.cheaper_than_eua ? 'pos' : 'warn'} title="Befund">
          {data.cheaper_than_eua
            ? `Zusätzliche Vermeidung durch Umdisponieren kostet ${fmt(data.slope_eur_t)} €/t und ist damit günstiger als ein Zertifikat (${fmt(data.eua)} €/t).`
            : `Zusätzliche Vermeidung durch Umdisponieren kostet ${fmt(data.slope_eur_t)} €/t, Zertifikate (${fmt(data.eua)} €/t) sind an diesem Tag günstiger.`}
          {' '}Der Erlös ist ohne Förderung negativ, weil Biomethan teuer ist. Das ist ehrlich gerechnet und kein Fehler.
        </Note>
      )}
    </PageShell>
  )
}
