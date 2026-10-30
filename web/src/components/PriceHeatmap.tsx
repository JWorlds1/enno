// Interaktive Preis-Heatmap (Ø Spotpreis nach Wochentag × Stunde) — live aus history.csv.
import { Fragment, useEffect, useState } from 'react'
import { fldApi, type HeatmapData } from '@/lib/api'

function color(v: number | null, min: number, max: number): string {
  if (v === null || max <= min) return 'var(--fld-soft)'
  const t = Math.max(0, Math.min(1, (v - min) / (max - min)))
  return `hsl(${Math.round(220 * (1 - t))}, 72%, 50%)` // blau (billig) → rot (teuer)
}

export function PriceHeatmap() {
  const [d, setD] = useState<HeatmapData | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fldApi.priceHeatmap().then(setD).catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
  }, [])

  if (err) return <div style={{ color: 'var(--fld-faint)', fontSize: 13 }}>Heatmap nicht verfügbar ({err}).</div>
  if (!d) return <div style={{ color: 'var(--fld-faint)' }}>lädt…</div>

  return (
    <div>
      <div className="heatmap-grid" style={{ display: 'grid', gridTemplateColumns: `36px repeat(24, minmax(0, 1fr))`, gap: 2, fontSize: 10 }}>
        <div />
        {d.hours.map((h) => <div key={h} style={{ textAlign: 'center', color: 'var(--fld-faint)' }}>{h % 3 === 0 ? h : ''}</div>)}
        {d.weekdays.map((wd, wi) => (
          <Fragment key={wd}>
            <div style={{ display: 'flex', alignItems: 'center', color: 'var(--fld-muted)', fontSize: 12 }}>{wd}</div>
            {d.matrix[wi].map((v, hi) => (
              <div key={`${wi}-${hi}`} title={`${wd} ${hi}:00 — ${v ?? '—'} €/MWh`}
                style={{ aspectRatio: '1', background: color(v, d.min, d.max), borderRadius: 3, minHeight: 14 }} />
            ))}
          </Fragment>
        ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12, fontSize: 12, color: 'var(--fld-muted)' }}>
        <span>{d.min} €/MWh</span>
        <div style={{ flex: 1, height: 8, borderRadius: 4, background: 'linear-gradient(90deg, hsl(220,72%,50%), hsl(110,72%,50%), hsl(0,72%,50%))' }} />
        <span>{d.max} €/MWh</span>
        <span style={{ color: 'var(--fld-faint)' }}>· billig → teuer (Ø über die Historie)</span>
      </div>
    </div>
  )
}
