// Cockpit — Empfehlung für morgen + Mehrwert pro Jahr (Hero), vier Kernzahlen, der Fahrplan über den Tag (Marktzeit).
import { useEffect, useState } from 'react'
import { Line } from 'react-chartjs-2'
import { askEnno } from '@/Enno'
import { fldApi, type DecisionOut, type Recommendation, type ValueOut } from '@/lib/api'
import { Card, CardGrid, ChartBox, ErrorBanner, PageShell, Section, Skeleton, dayWord, fmt, signed, starts } from '@/ui'

const longDate = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString('de-DE', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' })

export function DashboardPage() {
  const [rec, setRec] = useState<Recommendation | null>(null)
  const [val, setVal] = useState<ValueOut | null>(null)
  const [dec, setDec] = useState<DecisionOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.allSettled([fldApi.recommendation(), fldApi.value(), fldApi.decision()])
      .then(([r, b, d]) => {
        if (r.status === 'fulfilled') setRec(r.value)
        else setError(r.reason instanceof Error ? r.reason.message : String(r.reason))
        if (b.status === 'fulfilled') setVal(b.value)
        if (d.status === 'fulfilled') setDec(d.value)
      })
      .finally(() => setLoading(false))
  }, [])

  const k = rec?.kpis ?? {}
  const slots = rec?.slots ?? []
  const auction = k['price_basis'] === 'Auktion'
  const perYear = val ? Math.round(val.per_year_eur / 1000) * 1000 : null
  const uplift = typeof k['expected_uplift_eur'] === 'number' ? (k['expected_uplift_eur'] as number) : null
  const when = dayWord(rec?.target_day)
  const h2 = typeof k['h2_produced_mwh'] === 'number' ? (k['h2_produced_mwh'] as number) : 0

  const chartData = {
    // Marktzeit: der Strommarkt rechnet in Berliner Zeit, egal wo der Browser steht
    labels: slots.map((s) => (s.ts ? new Date(s.ts).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Berlin' }) : String(s.slot))),
    datasets: [
      { label: `Strompreis (${auction ? 'Auktion' : 'Prognose'}) €/MWh`, data: slots.map((s) => s.pred_price ?? null), borderColor: 'var(--c-price)', backgroundColor: 'transparent', yAxisID: 'yPrice', pointRadius: 0, borderWidth: 2, tension: 0.3 },
      { label: 'BHKW MW', data: slots.map((s) => s.bhkw_mw ?? null), borderColor: 'var(--brand-strong)', backgroundColor: 'var(--c-plasma-fill)', yAxisID: 'yPower', fill: true, pointRadius: 0, stepped: true as const },
      ...(h2 > 0 ? [{ label: 'Elektrolyse MW', data: slots.map((s) => -(s.electrolyser_mw ?? 0)), borderColor: 'var(--c-elektro)', backgroundColor: 'var(--c-elektro-fill)', yAxisID: 'yPower', fill: true, pointRadius: 0, stepped: true as const }] : []),
    ],
  }
  const chartOptions = {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: 'index' as const, intersect: false },
    scales: {
      x: { ticks: { maxTicksLimit: 12 }, grid: { display: false } },
      yPrice: { position: 'left' as const, title: { display: true, text: '€/MWh' } },
      // Elektrolyse = Stromverbrauch → unter der Nulllinie; Achse nur dann ins Negative
      yPower: { position: 'right' as const, title: { display: true, text: 'MW' }, grid: { drawOnChartArea: false }, min: h2 > 0 ? -0.6 : 0, max: 1.1 },
    },
    plugins: { legend: { position: 'bottom' as const } },
  }

  return (
    <PageShell title="Cockpit" actions={<a className="btn" href="/fld-api/report" target="_blank" rel="noreferrer">Report öffnen</a>}>
      <ErrorBanner error={error} />

      <section className="hero">
        {loading ? <Skeleton height={120} /> : (
          <div className="hero-row">
            <div style={{ maxWidth: 620 }}>
              <div className="eyebrow">Empfehlung für {rec ? longDate(rec.target_day) : '—'}{rec ? ` · ${auction ? 'Gebotsplan, bewertet zu Auktionspreisen' : 'Gebotsplan auf Preisprognose'}` : ''}</div>
              <h2>{dec?.label ?? 'Noch keine Empfehlung'}</h2>
              <div style={{ color: 'rgba(245,243,240,0.75)' }}>
                {dec?.summary ?? `BHKW ${fmt(k['bhkw_runtime_h'], 1)} h${h2 > 0 ? `, ${fmt(h2, 1)} MWh Wasserstoff` : ''}.`}
              </div>
              <div style={{ display: 'flex', gap: 10, marginTop: 18, flexWrap: 'wrap' }}>
                <button className="btn btn-primary" onClick={() => askEnno('Warum diese Strategie?')}>Warum? Frag Enno</button>
                <a className="btn btn-ghost" href="#/empfehlung">Fahrplan ansehen</a>
              </div>
            </div>
            <div className="hero-kpi">
              <div className="big">{perYear != null ? `≈ ${fmt(perYear)} €` : '—'}</div>
              <div style={{ color: 'rgba(245,243,240,0.75)', marginTop: 6 }}>mehr pro Jahr und MW als Dauerbetrieb</div>
              {val && <div style={{ color: 'rgba(245,243,240,0.55)', fontSize: 12, marginTop: 2 }}>{signed(val.pct_vs_flat)} % · an {val.days} Tagen nachgerechnet</div>}
            </div>
          </div>
        )}
      </section>

      <CardGrid min={220}>
        {loading ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} height={104} />) : <>
          <Card label={`Mehr als Dauerbetrieb ${when}`} value={uplift != null ? `${signed(uplift)} €` : '—'} sub={`${auction ? '' : 'erwartet laut Prognose · '}Erlös ${fmt(k['expected_revenue_eur'])} € statt ${fmt(k['flat_baseline_eur'])} €`} accent="green" />
          <Card label={`Strompreis ${when}`} value={`${fmt(k['pred_price_min'])}–${fmt(k['pred_price_max'])}`} sub={`€/MWh, ${auction ? 'Auktion' : 'Prognose'}`} />
          <Card label="BHKW-Laufzeit" value={`${fmt(k['bhkw_runtime_h'], 1)} h`} sub={starts(k['bhkw_starts'])} />
          <Card label="Treffsicherheit" value={val?.capture_pct != null ? `${fmt(val.capture_pct)} %` : '—'} sub={`vom möglichen Mehrerlös, ${val?.days ?? 0} Tage`} />
        </>}
      </CardGrid>

      <Section title="Fahrplan über den Tag" right={<a className="btn" href="#/backtest">Nachweis: Backtest →</a>}>
        <ChartBox height={360}>
          {slots.length > 0
            ? <Line data={chartData} options={chartOptions} />
            : <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--fld-faint)' }}>{loading ? 'lädt …' : 'Noch kein Fahrplan. Tageskette ausführen.'}</div>}
        </ChartBox>
      </Section>
    </PageShell>
  )
}
