// Schattenbetrieb — Empfehlung von FLD OS gegen die tatsächlich gefahrene Anlage, fair bei gleicher Energiemenge.
import { useState, type ChangeEvent } from 'react'
import { shadowApi } from '@/lib/api'
import { Card, CardGrid, ErrorBanner, Note, PageShell, Section, Skeleton, fmt, useApi } from '@/ui'

const sign = (v: number) => `${v >= 0 ? '+' : ''}${fmt(v)} €`

export function ShadowPage() {
  const [rev, setRev] = useState(0)
  const { data, error, loading } = useApi(() => shadowApi.get(), [rev])
  const [msg, setMsg] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    setProblem(null)
    try {
      const r = await shadowApi.upload(await f.text())
      setMsg(`${r.rows} Viertelstunden aus ${f.name} übernommen.`)
      setRev((x) => x + 1)
    } catch (err) {
      setMsg(null)
      setProblem(`Nicht übernommen (${f.name}): ${err instanceof Error ? err.message.replace(/^\/measurements → \d+: /, '') : String(err)}`)
    }
  }

  const s = data?.summary
  return (
    <PageShell title="Schattenbetrieb" subtitle="Die Anlage fährt wie bisher, FLD OS rechnet jeden Tag mit. Hier steht, was die Empfehlung gegenüber dem tatsächlichen Betrieb gebracht hätte."
      actions={<label className="btn btn-primary">Messdaten importieren (CSV)<input type="file" accept=".csv,.txt" onChange={onFile} style={{ display: 'none' }} /></label>}>
      <ErrorBanner error={error} />
      {problem && <Note tone="warn" alert>{problem}</Note>}
      {msg && <Note tone="pos">{msg}</Note>}
      <CardGrid min={220}>
        {loading && !data ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} height={104} />) : <>
          <Card label="Verglichene Tage" value={fmt(s?.days ?? 0)} sub={`${fmt(data?.measurements ?? 0)} Messwerte (¼ h)`} />
          <Card label="Mehrerlös bei gleicher Energie" value={s && s.days ? sign(s.extra_same_energy_eur) : '—'} sub="Empfehlung ggü. tatsächlichem Betrieb" accent="green" />
          <Card label="Je Tag" value={s?.per_day_eur != null ? sign(s.per_day_eur) : '—'} sub="im Mittel" />
        </>}
      </CardGrid>
      <Section title="Tag für Tag">
        {data && data.days.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table className="nowrap">
              <thead><tr><th>Liefertag</th><th>Energie empfohlen</th><th>gefahren</th><th>Ø-Preis empfohlen</th><th>gefahren</th><th>Mehrerlös gleiche Energie</th></tr></thead>
              <tbody>{data.days.map((d) => (
                <tr key={d.day}>
                  <td>{new Date(`${d.day}T12:00:00`).toLocaleDateString('de-DE')}</td>
                  <td>{fmt(d.energy_rec_mwh, 1)} MWh</td><td>{fmt(d.energy_meas_mwh, 1)} MWh</td>
                  <td>{fmt(d.price_rec_eur_mwh, 1)} €/MWh</td><td>{fmt(d.price_meas_eur_mwh, 1)} €/MWh</td>
                  <td style={{ fontWeight: 700, color: d.extra_same_energy_eur >= 0 ? 'var(--c-pos)' : 'var(--c-neg)' }}>{sign(d.extra_same_energy_eur)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <div style={{ color: 'var(--fld-faint)' }}>Noch kein vergleichbarer Tag. Messdaten importieren: CSV mit Zeilen <code>zeit;leistung_kw</code> (Viertelstunden oder feiner, Marktzeit Berlin). Ein Tag zählt ab 90 % Abdeckung und vorhandener Empfehlung.</div>}
      </Section>
      <Note title="So wird verglichen">Fährt die Anlage mehr oder weniger Energie als empfohlen, wäre ein reiner Erlösvergleich schief. Deshalb: erzielter Durchschnittspreis je MWh (Day-Ahead) der Empfehlung minus der des tatsächlichen Betriebs, mal gefahrene Energie. Wärme- und EEG-Erlöse sind bei gleicher Energiemenge gleich und kürzen sich.</Note>
    </PageShell>
  )
}
