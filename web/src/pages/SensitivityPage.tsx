// Sensitivität — Tornado: Welche Annahme bewegt den Tageserlös am stärksten (±30 %)?
import { useEffect, useState } from 'react'
import { Bar } from 'react-chartjs-2'
import { fldApi, marketGas, type PtxMode } from '@/lib/api'
import { Card, CardGrid, ChartBox, ErrorBanner, Note, PageShell, Section, Segmented, Skeleton, fmt, useApi, useDebounced } from '@/ui'

function Slider({ label, unit, value, min, max, onChange }: { label: string; unit: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <label style={{ display: 'grid', gap: 4, minWidth: 180, flex: 1 }}>
      <span style={{ fontSize: 13, color: 'var(--fld-muted)' }}>{label}: <strong style={{ color: 'var(--fld-text)' }}>{value} {unit}</strong></span>
      <input type="range" min={min} max={max} value={value} onChange={(e) => onChange(Number(e.target.value))} style={{ accentColor: 'var(--brand)', border: 0 }} />
    </label>
  )
}

export function SensitivityPage() {
  // Start wie Cockpit/Was-wäre-wenn: Gas heute (TTF + Aufschlag), Anlage mit Elektrolyseur
  const [gas, setGas] = useState(120)
  const [h2, setH2] = useState(100)
  const [co2, setCo2] = useState(79)
  const [mode, setMode] = useState<PtxMode>('electro')
  useEffect(() => { marketGas().then((m) => m && setGas(m.gas)).catch(() => { /* Startwert bleibt */ }) }, [])
  const q = useDebounced({ gas, h2, co2, mode }, 350)  // Regler feuern je Schritt — erst nach Pause rechnen
  const { data, error, loading } = useApi(() => fldApi.sensitivity(q), [q])

  const chart = data && {
    labels: data.bars.map((b) => b.label),
    datasets: [
      { label: '−30 %', data: data.bars.map((b) => [data.base_net, b.low_net] as [number, number]), backgroundColor: 'var(--c-elektro)', grouped: false },
      { label: '+30 %', data: data.bars.map((b) => [data.base_net, b.high_net] as [number, number]), backgroundColor: 'var(--brand)', grouped: false },
    ],
  }

  return (
    <PageShell title="Sensitivität" subtitle="Der jüngste Fahrplantag wird je Annahme mit −30 % und +30 % neu optimiert. Die Balkenlänge zeigt, wie stark die Annahme den Netto-Tageserlös bewegt.">
      <Section title="Basisannahmen">
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <Slider label="Gaspreis" unit="€/MWh" value={gas} min={20} max={150} onChange={setGas} />
          <Slider label="H₂-Wert" unit="€/MWh" value={h2} min={40} max={250} onChange={setH2} />
          <Slider label="CO₂-/CDR-Preis" unit="€/t" value={co2} min={0} max={250} onChange={setCo2} />
          <Segmented value={mode} onChange={setMode} options={[{ value: 'none', label: 'Nur BHKW' }, { value: 'electro', label: 'Elektrolyse' }, { value: 'plasma', label: 'Plasma' }]} />
        </div>
      </Section>
      <ErrorBanner error={error} />
      <CardGrid>
        {!data ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} />) : <>
          <Card label="Netto-Tageserlös (Basis)" value={`${fmt(data.base_net)} €`} sub={loading ? 'rechnet…' : data.with_eeg ? 'inkl. EEG, nach Gaskosten (wie Was-wäre-wenn)' : 'nach Gaskosten, ohne EEG'} accent={data.base_net >= 0 ? 'green' : 'red'} />
          <Card label="Stärkster Hebel" value={data.bars[0]?.label ?? '—'} sub={`Spanne ${fmt(data.bars[0]?.swing)} €`} accent="amber" />
          <Card label="Schwächster Hebel" value={data.bars.at(-1)?.label ?? '—'} sub={`Spanne ${fmt(data.bars.at(-1)?.swing)} €`} />
        </>}
      </CardGrid>

      <Section title="Tornado">
        <ChartBox height={260}>
          {chart ? <Bar data={chart} options={{
            indexAxis: 'y', responsive: true, maintainAspectRatio: false,
            scales: { x: { title: { display: true, text: 'Netto-Tageserlös (€)' } } },
            plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: (c) => {
              const b = data!.bars[c.dataIndex]; const lo = c.datasetIndex === 0
              return `${lo ? b.low_value : b.high_value}: ${fmt(lo ? b.low_net : b.high_net)} €`
            } } } },
          }} /> : <Skeleton height="100%" />}
        </ChartBox>
      </Section>

      <Note title="Einordnung">Der Gaspreis wirkt fast eins zu eins auf das Netto, weil die Tages-Gasmenge fest ist. H₂- und CO₂-Preis wirken nur, soweit der Fahrplan Gas in den PtX- bzw. Plasma-Pfad routet.</Note>
    </PageShell>
  )
}
