// Plasma-Pyrolyse vs. Elektrolyse vs. nur Strom — Gas-Routing je Viertelstunde auf Ist-Preisen.
import { useState } from 'react'
import { Bar } from 'react-chartjs-2'
import { fldApi } from '@/lib/api'
import { Card, CardGrid, ChartBox, ErrorBanner, Note, PageShell, Section, Segmented, Skeleton, fmt, signed, useApi } from '@/ui'

export function PlasmaPage() {
  const [days, setDays] = useState(10)
  const { data, error, loading } = useApi(() => fldApi.plasmaCompare(days), [days])

  const chart = data && {
    labels: data.rows.map((r) => r.day.slice(5)),
    datasets: [
      { label: 'Nur Strom', data: data.rows.map((r) => r.power), backgroundColor: 'var(--c-price)' },
      { label: '+ Elektrolyse', data: data.rows.map((r) => r.electro), backgroundColor: 'var(--c-elektro)' },
      { label: '+ Plasma-Pyrolyse', data: data.rows.map((r) => r.pyro), backgroundColor: 'var(--brand)' },
    ],
  }
  const pyroWins = data ? data.uplift_pyro > data.uplift_electro : false

  return (
    <PageShell title="Plasma vs. Elektrolyse" subtitle="Plasma-Pyrolyse spaltet Biomethan aus demselben Speicher in Wasserstoff und festen Kohlenstoff. Je Slot entscheidet das Modell: Gas verstromen oder zu H₂ + C veredeln."
      actions={<Segmented value={days} onChange={setDays} options={[{ value: 10, label: '10 Tage' }, { value: 30, label: '30 Tage' }]} />}>
      <ErrorBanner error={error} />
      <CardGrid>
        {loading || !data ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} />) : <>
          <Card label="Ø nur Strom" value={`${fmt(data.avg.power)} €`} sub="pro Tag" />
          <Card label="Mehrwert Elektrolyse" value={`${signed(data.uplift_electro)} €`} sub="pro Tag vs. nur Strom" accent="blue" />
          <Card label="Mehrwert Plasma" value={`${signed(data.uplift_pyro)} €`} sub="pro Tag vs. nur Strom" accent="amber" />
          <Card label="Kohlenstoff-Gutschrift" value={`${fmt(data.carbon_credit_eur_t)} €/t`} sub="CO₂-Äquivalent (EUA-Niveau)" />
        </>}
      </CardGrid>

      <Section title="Tageserlös je Betriebsmodus">
        <ChartBox height={360}>
          {chart ? <Bar data={chart} options={{ responsive: true, maintainAspectRatio: false, scales: { y: { title: { display: true, text: '€ / Tag' } } }, plugins: { legend: { position: 'bottom' } } }} /> : <Skeleton height="100%" />}
        </ChartBox>
      </Section>

      {data && <Section title="Stoffströme Plasma-Pfad">
        <table>
          <thead><tr><th>Tag</th><th>Gas → Pyrolyse MWh</th><th>H₂ MWh</th><th>Kohlenstoff t</th><th>Plasma − Elektrolyse €</th></tr></thead>
          <tbody>{data.rows.map((r) => (
            <tr key={r.day}><td>{r.day}</td><td>{fmt(r.gas_pyro_mwh, 2)}</td><td>{fmt(r.h2_mwh, 2)}</td><td>{fmt(r.carbon_t, 3)}</td>
              <td style={{ color: r.pyro >= r.electro ? 'var(--c-pos)' : 'var(--c-neg)' }}>{fmt(r.pyro - r.electro)}</td></tr>
          ))}</tbody>
        </table>
      </Section>}

      {data && <Note tone={pyroWins ? 'pos' : 'warn'} title="Befund">
        {pyroWins
          ? `Im gewählten Zeitraum liegt Plasma-Pyrolyse vorn (+${fmt(data.uplift_pyro - data.uplift_electro)} €/Tag gegenüber Elektrolyse).`
          : `Im gewählten Zeitraum liegt die Elektrolyse vorn (${fmt(data.uplift_electro - data.uplift_pyro)} €/Tag). Der Vorteil der Pyrolyse hängt am Kohlenstoff-Preis, siehe CDR-Sensitivität.`}
      </Note>}
    </PageShell>
  )
}
