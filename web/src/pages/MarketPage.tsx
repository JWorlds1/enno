// Markt-Kontext — TTF-Gas- & EUA-CO₂-Trend + aFRR/FCR-Regelenergiepreise.
import { useEffect, useState } from 'react'
import { Line } from 'react-chartjs-2'
import { fldApi, type FundamentalPoint, type RegelPoint } from '@/lib/api'
import { Card, Section, PageShell, ErrorBanner, fmt } from '@/ui'

export function MarketPage() {
  const [mk, setMk] = useState<FundamentalPoint[]>([])
  const [re, setRe] = useState<RegelPoint[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.allSettled([fldApi.market(), fldApi.regelenergie()]).then(([m, r]) => {
      if (m.status === 'fulfilled') setMk([...m.value].sort((a, b) => a.day.localeCompare(b.day)))
      else setError(m.reason instanceof Error ? m.reason.message : String(m.reason))
      if (r.status === 'fulfilled') setRe([...r.value].sort((a, b) => a.day.localeCompare(b.day)))
    })
  }, [])

  const last = mk[mk.length - 1]
  const fundChart = {
    labels: mk.map((p) => p.day),
    datasets: [
      { label: 'TTF-Gas €/MWh', data: mk.map((p) => p.ttf_gas_eur_mwh), borderColor: 'var(--c-plasma)', backgroundColor: 'transparent', yAxisID: 'yGas', pointRadius: 0, tension: 0.2 },
      { label: 'EUA-CO₂ €/t', data: mk.map((p) => p.eua_co2_eur_t), borderColor: 'var(--c-pos)', backgroundColor: 'transparent', yAxisID: 'yCo2', pointRadius: 0, tension: 0.2 },
    ],
  }

  const days = [...new Set(re.map((r) => r.day))]
  const reChart = {
    labels: days,
    datasets: [
      { label: 'aFRR+ €/MW·h', data: days.map((d) => re.find((r) => r.day === d && r.product === 'afrr_pos')?.price_eur_mw_h ?? null), borderColor: 'var(--c-elektro)', backgroundColor: 'transparent', pointRadius: 0, tension: 0.2 },
      { label: 'aFRR− €/MW·h', data: days.map((d) => re.find((r) => r.day === d && r.product === 'afrr_neg')?.price_eur_mw_h ?? null), borderColor: 'var(--c-h2)', backgroundColor: 'transparent', pointRadius: 0, tension: 0.2 },
      { label: 'FCR €/MW·h', data: days.map((d) => re.find((r) => r.day === d && r.product === 'fcr')?.price_eur_mw_h ?? null), borderColor: 'var(--c-accent2)', backgroundColor: 'transparent', pointRadius: 0, tension: 0.2 },
    ],
  }

  return (
    <PageShell title="Markt-Kontext" subtitle="Die Umgebungsdaten hinter dem Fahrplan: Gas, CO₂ und Regelenergie.">
      <ErrorBanner error={error} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 22 }}>
        <Card label="TTF-Gas (aktuell)" value={`${fmt(last?.ttf_gas_eur_mwh, 1)} €/MWh`} sub={last?.day} accent="amber" />
        <Card label="EUA-CO₂ (aktuell)" value={`${fmt(last?.eua_co2_eur_t, 1)} €/t`} sub={last?.day} accent="green" />
        <Card label="Markttage" value={fmt(mk.length)} sub="Fundamentaldaten" />
      </div>
      <Section title="Gas- & CO₂-Preis-Trend">
        <div style={{ height: 320 }}>
          {mk.length ? <Line data={fundChart} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { ticks: { maxTicksLimit: 12 } }, yGas: { position: 'left', title: { display: true, text: '€/MWh' } }, yCo2: { position: 'right', title: { display: true, text: '€/t' }, grid: { drawOnChartArea: false } } } }} />
            : <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--fld-faint)' }}>lädt…</div>}
        </div>
      </Section>
      <Section title="Regelenergie — aFRR & FCR Kapazitätspreise">
        <div style={{ height: 280 }}>
          {re.length ? <Line data={reChart} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { y: { title: { display: true, text: '€/MW·h' } } } }} />
            : <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--fld-faint)' }}>lädt…</div>}
        </div>
      </Section>
    </PageShell>
  )
}
