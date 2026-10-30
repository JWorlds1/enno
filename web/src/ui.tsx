// Gemeinsame UI-Bausteine (Card, Section, PageShell, Segmented, Note, Skeleton, useApi).
// Farben ausschließlich über Tokens aus theme.css — dadurch wirken Marke und Hell/Dunkel überall.
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import './chart-setup'

export const fmt = (v: unknown, dp = 0): string =>
  typeof v === 'number' && isFinite(v) ? v.toLocaleString('de-DE', { maximumFractionDigits: dp }) : '—'

/** Mit Vorzeichen: „+12“ / „-12“ — nie „+-12“. */
export const signed = (v: unknown, dp = 0): string =>
  typeof v === 'number' && isFinite(v) ? `${v >= 0 ? '+' : ''}${fmt(v, dp)}` : '—'

/** „morgen“ nur, wenn der Liefertag in Marktzeit wirklich morgen ist — sonst „heute“ bzw. „am 15.10.“ (Review M-07). */
export function dayWord(iso?: string | null): string {
  if (!iso) return 'morgen'
  const today = new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Berlin' })  // YYYY-MM-DD
  const diff = Math.round((Date.parse(`${iso}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000)
  return diff === 1 ? 'morgen' : diff === 0 ? 'heute' : `am ${iso.split('-').reverse().slice(0, 2).join('.')}.`
}

export type Accent = 'green' | 'red' | 'amber' | 'blue' | 'pink' | 'none'
export const starts = (n: unknown): string => `${fmt(n)} ${n === 1 ? 'Start' : 'Starts'}`

/** Zeitpunkt in Marktzeit (Europe/Berlin) — der Strommarkt rechnet so, unabhängig von der Zeitzone des Browsers. */
export const marketTime = (iso: string, withDate = true): string =>
  new Date(iso).toLocaleString('de-DE', { timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit', ...(withDate ? { day: '2-digit', month: '2-digit' } : {}) })

export const ACCENT: Record<Accent, string> = {
  green: 'var(--c-pos)', red: 'var(--c-neg)', amber: 'var(--brand-strong)', blue: 'var(--c-elektro)', pink: 'var(--c-h2)', none: 'var(--fld-border)',
}

export function Card({ label, value, sub, accent = 'none' }: { label: string; value: string; sub?: string; accent?: Accent }) {
  return (
    <div className="card kpi">
      <div className="eyebrow kpi-label" title={label}>{label}</div>
      <div className="num kpi-value" style={{ color: accent === 'none' ? 'var(--fld-text)' : ACCENT[accent] }}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  )
}

export function CardGrid({ children, min = 200 }: { children: ReactNode; min?: number }) {
  return <div className="card-grid" style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${min}px, 1fr))`, gap: 14, marginBottom: 22 }}>{children}</div>
}

export function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="card" style={{ padding: 18, marginBottom: 22 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <h2 className="section-title">{title}</h2>
        {right}
      </div>
      <div className="section-body">{children}</div>
    </section>
  )
}

export function PageShell({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, flexWrap: 'wrap', marginBottom: 6 }}>
        <h1 className="page-title">{title}</h1>
        {actions}
      </div>
      {subtitle && <p style={{ color: 'var(--fld-muted)', margin: '0 0 22px', maxWidth: 820 }}>{subtitle}</p>}
      {children}
    </div>
  )
}

/** Befund-/Einordnungskasten: was die Zahl bedeutet und wo ihre Grenze liegt. */
export function Note({ tone = 'info', title, children, alert = false }: { tone?: 'info' | 'warn' | 'pos'; title?: string; children: ReactNode; alert?: boolean }) {
  return (
    <div className={`note note-${tone}`} role={alert ? 'alert' : undefined}>
      {title && <strong style={{ display: 'block', marginBottom: 4 }}>{title}</strong>}
      {children}
    </div>
  )
}

export function Segmented<T extends string | number>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="segmented" role="group">
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  )
}

export function ErrorBanner({ error }: { error: string | null }) {
  if (!error) return null
  return <Note tone="warn" alert>Backend nicht erreichbar oder Daten fehlen ({error}).</Note>
}

export function Skeleton({ height = 92, radius = 12 }: { height?: number | string; radius?: number }) {
  return <div className="skeleton" style={{ height, borderRadius: radius }} />
}

export function ChartBox({ height = 340, children, style }: { height?: number; children: ReactNode; style?: CSSProperties }) {
  return <div style={{ position: 'relative', height, ...style }}>{children}</div>
}

/** Lädt einen Endpoint; `deps` steuern das Neuladen (z. B. Regler). */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let alive = true
    setLoading(true)
    load()
      .then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e) => { if (alive) setError(e instanceof Error ? e.message : String(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, error, loading }
}

/** Wert erst nach `ms` Ruhe übernehmen (Regler, Eingaben). Objekt-Identität bleibt bis zur Änderung stabil. */
export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  const key = JSON.stringify(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ms])
  return v
}
