// Risiko — mean-CVaR-Effizienzfront: Wie viel erwarteten Erlös kostet Schutz vor schlechten Preistagen?
import { Scatter } from 'react-chartjs-2'
import { fldApi } from '@/lib/api'
import { Card, CardGrid, ChartBox, ErrorBanner, Note, PageShell, Section, Skeleton, fmt, useApi } from '@/ui'

export function RiskPage() {
  const { data, error, loading } = useApi(fldApi.risk)

  const chart = data && {
    datasets: [{
      label: 'Effizienzfront (λ = Risikoaversion)',
      data: data.frontier.map((f) => ({ x: f.cvar, y: f.expected })),
      borderColor: 'var(--brand-strong)', backgroundColor: 'var(--brand)', showLine: true, pointRadius: 5, tension: 0.2,
    }],
  }

  return (
    <PageShell title="Risiko & Robustheit" subtitle="Zweistufige stochastische Optimierung über Preisszenarien. Die Front zeigt, wie viel erwarteten Erlös ein robusterer Fahrplan kostet, gemessen am Mittel der schlechtesten 20 % der Szenarien (CVaR).">
      <ErrorBanner error={error} />
      {loading && <Note>Erste Berechnung löst {`~`}20 MILPs, das dauert bis zu 30 s. Danach kommt das Ergebnis aus dem Cache.</Note>}
      <CardGrid>
        {loading || !data ? Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} />) : <>
          <Card label="Stochastisch (RP)" value={`${fmt(data.rp)} €`} sub={`Tag ${data.day} · ${data.scenarios} Szenarien`} />
          <Card label="Deterministisch (EEV)" value={`${fmt(data.eev)} €`} sub="Plan auf Punktprognose" />
          <Card label="Perfekte Info (WS)" value={`${fmt(data.ws)} €`} sub="theoretische Obergrenze" />
          <Card label="Wert der Stochastik" value={`${fmt(data.vss, 1)} €`} sub="VSS = RP − EEV" accent={data.vss > 0 ? 'green' : 'none'} />
          <Card label="Wert perfekter Info" value={`${fmt(data.evpi, 1)} €`} sub="EVPI = WS − RP" accent="amber" />
        </>}
      </CardGrid>

      <Section title="mean-CVaR-Effizienzfront">
        <ChartBox>
          {chart ? <Scatter data={chart} options={{
            responsive: true, maintainAspectRatio: false,
            scales: { x: { title: { display: true, text: `CVaR ${data ? data.alpha * 100 : 20} % (€, schlechteste Szenarien)` } }, y: { title: { display: true, text: 'Erwarteter Erlös (€)' } } },
            plugins: { tooltip: { callbacks: { label: (c) => `λ=${data!.frontier[c.dataIndex].lam}: E=${fmt(c.parsed.y)} €, CVaR=${fmt(c.parsed.x)} €` } } },
          }} /> : <Skeleton height="100%" />}
        </ChartBox>
      </Section>

      {data && <Section title="Stützpunkte">
        <table>
          <thead><tr><th>λ</th><th>Erwarteter Erlös €</th><th>CVaR €</th><th>BHKW-Laufzeit h</th></tr></thead>
          <tbody>{data.frontier.map((f) => (
            <tr key={f.lam}><td>{f.lam}</td><td>{fmt(f.expected, 1)}</td><td>{fmt(f.cvar, 1)}</td><td>{fmt(f.bhkw_h, 2)}</td></tr>
          ))}</tbody>
        </table>
      </Section>}

      <Note title="Einordnung">
        Steigt λ, schützt sich der Fahrplan gegen Niedrigpreis-Tails: Der erwartete Erlös sinkt leicht, das Worst-Case-Mittel steigt.
        Die Differenz sind die Kosten der Robustheit. Grenze: Die Szenarien stammen aus einem Block-Bootstrap der Prognosefehler,
        echte Anlagendaten sind noch nicht eingeflossen.
      </Note>
    </PageShell>
  )
}
