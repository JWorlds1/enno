// Was-wäre-wenn — gemeinsam optimieren: Annahmen verändern, Tag live neu rechnen, Szenarien merken und vergleichen.
import { useEffect, useMemo, useRef, useState } from 'react'
import { Line } from 'react-chartjs-2'
import { fldApi, marketGas, type DecisionOut, type PtxMode, type Recommendation, type WhatifOut } from '@/lib/api'
import { Card, Note, PageShell, Section, Segmented, fmt, marketTime, signed, starts } from '@/ui'

const ALGOS = [
  { value: 'whatif', label: 'Standard (MILP)' },
  { value: 'schedule', label: 'Betriebsnah (Mindestlauf, Wärme)' },
  { value: 'coopt', label: 'Spot + Regelenergie' },
  { value: 'stochastic', label: 'Stochastisch (Preisszenarien)' },
  { value: 'cvar', label: 'Risikoavers (CVaR)' },
]
const MODES: { value: PtxMode; label: string }[] = [
  { value: 'none', label: 'nur BHKW' }, { value: 'electro', label: 'Elektrolyse' }, { value: 'plasma', label: 'Plasma' },
]
const STORE = 'fldos.szenarien'

interface Params { gas: number; h2: number; co2: number; mode: PtxMode; algo: string }
interface Scenario { id: number; name: string; p: Params; r: WhatifOut }

function Slider({ label, min, max, step, value, unit, hint, onChange }: {
  label: string; min: number; max: number; step: number; value: number; unit: string; hint?: string; onChange: (v: number) => void
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
        <span style={{ color: 'var(--fld-text)', fontWeight: 500 }}>{label}</span>
        <span style={{ fontWeight: 700 }}>{value} {unit}</span>
      </div>
      <input type="range" aria-label={label} min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} style={{ width: '100%' }} />
      {hint && <div style={{ fontSize: 11, color: 'var(--fld-faint)', marginTop: 2 }}>{hint}</div>}
    </div>
  )
}

function loadScenarios(): Scenario[] {
  try { return JSON.parse(localStorage.getItem(STORE) ?? '[]') as Scenario[] } catch { return [] }
}

const modeLabel = (m: PtxMode) => MODES.find((x) => x.value === m)?.label ?? m
const algoLabel = (a: string) => ALGOS.find((x) => x.value === a)?.label ?? a
/** Was der Optimierer tatsächlich rechnet: „Betriebsnah“ nutzt feste Annahmen (Elektrolyse, H₂/CO₂ fest), „Spot + Regelenergie“ kennt keine Pyrolyse. */
const IGNORES_PTX = (a: string) => a === 'schedule'
const techLabel = (p: Params) =>
  IGNORES_PTX(p.algo) ? 'Elektrolyse (fest)' : p.algo === 'coopt' && p.mode === 'plasma' ? 'nur BHKW (ohne Plasma)' : modeLabel(p.mode)
/** Das eine Netto im System: inkl. Marktprämie + Flexzuschlag, sobald der Monatsmarktwert bekannt ist. */
const netOf = (r: WhatifOut) => r.net_eeg_eur ?? r.net_eur
// ★ vergleicht, was die Tabelle zeigt (ganze €): kein Stern für einen Unterschied von Cent, der nicht zu sehen ist
const shownNet = (r: WhatifOut) => Math.round(netOf(r))

export function WhatifPage() {
  // Start = Anlage wie im Cockpit geplant (BHKW + 0,5-MW-Elektrolyseur) → dieselben Zahlen wie dort
  const [p, setP] = useState<Params>({ gas: 120, h2: 100, co2: 79, mode: 'electro', algo: 'whatif' })
  const [gasHint, setGasHint] = useState<string>()
  const [rec, setRec] = useState<Recommendation | null>(null)
  const [dec, setDec] = useState<DecisionOut | null>(null)
  // Ergebnis immer mit den Annahmen, zu denen es gehört — sonst merkt „Szenario merken“ neue Regler mit altem Ergebnis
  const [shown, setShown] = useState<{ p: Params; r: WhatifOut } | null>(null)
  const res = shown?.r ?? null
  const seq = useRef(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [scen, setScen] = useState<Scenario[]>(loadScenarios)
  const set = <K extends keyof Params>(k: K) => (v: Params[K]) => setP((x) => ({ ...x, [k]: v }))

  // Startwert Gas = Biomethan heute: TTF (Markt) + Biomethan-Aufschlag (Anlagendaten).
  useEffect(() => {
    fldApi.recommendation().then(setRec).catch(() => { /* Untertitel ohne Datum */ })
    fldApi.decision().then(setDec).catch(() => { /* ohne Bezug zum Cockpit */ })
    marketGas().then((m) => {
      if (!m) return
      setP((x) => ({ ...x, gas: m.gas }))
      setGasHint(`Start: TTF ${fmt(m.ttf, 1)} + Biomethan-Aufschlag ${fmt(m.premium)} €/MWh`)
    }).catch(() => { /* Startwert bleibt — Rechnung funktioniert trotzdem */ })
  }, [])

  useEffect(() => {
    const id = ++seq.current
    setBusy(true)
    const t = setTimeout(() => {
      fldApi.whatif(p)
        // nur die Antwort zur letzten Eingabe zählt: eine langsamere ältere Rechnung überschreibt sie nicht
        .then((r) => { if (id === seq.current) { setShown({ p, r }); setError(null) } })
        .catch((e: unknown) => { if (id === seq.current) setError(e instanceof Error ? e.message : String(e)) })
        .finally(() => { if (id === seq.current) setBusy(false) })
    }, 300)
    return () => clearTimeout(t)
  }, [p])

  useEffect(() => { try { localStorage.setItem(STORE, JSON.stringify(scen)) } catch { /* privat/blockiert: nur Sitzung */ } }, [scen])
  // zweiter Tab: gemerkte Szenarien übernehmen statt sie beim nächsten Schreiben zu überschreiben
  useEffect(() => {
    const on = (e: StorageEvent) => { if (e.key === STORE) setScen(loadScenarios()) }
    window.addEventListener('storage', on)
    return () => window.removeEventListener('storage', on)
  }, [])

  const keep = () => shown && !busy && setScen((s) => [...s, { id: Date.now(), name: `Szenario ${s.length + 1}`, p: shown.p, r: shown.r }])
  // ★ nach Netto inkl. EEG: der Mehrerlös hängt nicht vom Gaspreis ab und trennt Gasvarianten nicht
  const top = scen.length ? Math.max(...scen.map((s) => shownNet(s.r))) : null
  const best = scen.filter((s) => shownNet(s.r) === top).length === 1 ? top : null  // nur für ein eindeutig bestes Szenario

  const breakdown = useMemo(() => res ? [
    { label: 'Strom (Spot)', v: res.spot }, { label: 'Wärme-Gutschrift', v: res.heat }, { label: 'Wasserstoff', v: res.h2_eur },
    { label: 'CO₂ / Kohlenstoff', v: res.carbon_eur },
    ...(res.eeg_premium_eur != null ? [{ label: 'EEG-Marktprämie', v: res.eeg_premium_eur }] : []),
    ...(res.flex_eur ? [{ label: 'Flexibilitätszuschlag', v: res.flex_eur }] : []),
    { label: '− Strombezug', v: -res.elcost }, { label: '− Gaskosten', v: -res.gas_cost },
  ] : [], [res])
  const scale = Math.max(1, ...breakdown.map((b) => Math.abs(b.v)))

  const chart = res ? {
    // Uhrzeit aus den Zeitstempeln des Fahrplans (Marktzeit; an Umstellungstagen 92/100 Viertelstunden)
    labels: res.bhkw.map((_, i) => {
      const ts = rec?.slots?.length === res.bhkw.length ? rec.slots[i].ts : null
      return ts ? marketTime(ts, false) : `${String(Math.floor(i / 4)).padStart(2, '0')}:${String((i % 4) * 15).padStart(2, '0')}`
    }),
    datasets: [
      { label: 'BHKW MW', data: res.bhkw, borderColor: 'var(--c-pos)', backgroundColor: 'var(--c-pos-fill)', fill: true, pointRadius: 0, stepped: true as const },
      ...(res.electro.some((v) => v > 0) ? [{ label: 'Elektrolyse MW', data: res.electro.map((v) => -v), borderColor: 'var(--c-elektro)', backgroundColor: 'var(--c-elektro-fill)', fill: true, pointRadius: 0, stepped: true as const }] : []),
      ...(res.pyro.some((v) => v > 0) ? [{ label: 'Pyrolyse (Gas)', data: res.pyro, borderColor: 'var(--c-plasma)', backgroundColor: 'var(--c-plasma-fill)', fill: true, pointRadius: 0, stepped: true as const }] : []),
    ],
  } : null

  const day = rec ? new Date(`${rec.target_day}T12:00:00`).toLocaleDateString('de-DE', { weekday: 'long', day: '2-digit', month: '2-digit' }) : null
  const auction = rec?.kpis?.['price_basis'] === 'Auktion'
  const basis = auction ? 'Auktionspreisen' : 'Preisprognosen'
  // Start = Cockpit gilt nur vor der Auktion und ohne Regelenergie — sonst den Unterschied erklären, nicht verstecken
  const reserve = dec?.strategy === 'REGELENERGIE_RESERVE'
  const cockpit = rec?.kpis?.['expected_uplift_eur'] as number | undefined

  return (
    <PageShell title="Was-wäre-wenn" subtitle={`Annahmen gemeinsam verändern — der Tag wird sofort neu optimiert.${day ? ` Rechnet mit den ${basis} für ${day}` : ''}`}>
      <div className="whatif-grid">
        <div className="panel">
          <div style={{ fontWeight: 600, marginBottom: 16 }}>Annahmen {busy && <span style={{ fontSize: 12, color: 'var(--fld-faint)' }}>· rechnet …</span>}</div>
          <Slider label="Gaspreis (Biomethan)" min={20} max={200} step={1} value={p.gas} unit="€/MWh" hint={gasHint} onChange={set('gas')} />
          <Slider label="H₂-Wert" min={50} max={250} step={1} value={p.h2} unit="€/MWh" onChange={set('h2')} hint={IGNORES_PTX(p.algo) ? 'wirkt bei „Betriebsnah“ nicht (feste Annahmen)' : undefined} />
          <Slider label="CO₂ / Kohlenstoff" min={0} max={300} step={1} value={p.co2} unit="€/t" onChange={set('co2')} hint={IGNORES_PTX(p.algo) ? 'wirkt bei „Betriebsnah“ nicht (feste Annahmen)' : undefined} />
          <div style={{ fontSize: 13, fontWeight: 500, margin: '10px 0 6px' }}>Technik</div>
          <Segmented value={p.mode} options={MODES} onChange={set('mode')} />
          <div style={{ fontSize: 13, fontWeight: 500, margin: '16px 0 6px' }}>Optimierer</div>
          <select aria-label="Optimierer" value={p.algo} onChange={(e) => set('algo')(e.target.value)} className="select">
            {ALGOS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
          </select>
          {techLabel(p) !== modeLabel(p.mode) && <div style={{ fontSize: 11, color: 'var(--fld-faint)', marginTop: 6 }}>Gerechnet wird: {techLabel(p)}</div>}
          <button className="btn btn-primary" style={{ width: '100%', marginTop: 18 }} onClick={keep} disabled={!shown || busy}>Szenario merken</button>
        </div>

        <div style={{ minWidth: 0 }}>
          {error && <Note tone="warn" alert>Fehler: {error}</Note>}
          {(auction || reserve) && (
            <Note title="Bezug zum Cockpit">
              Das Cockpit zeigt den Gebotsplan ({signed(cockpit)} €){reserve ? ' inklusive Regelenergie' : ''}, der vor der Auktion feststand.
              {auction ? ' Hier wird der Tag mit den inzwischen bekannten Auktionspreisen neu optimiert — der Unterschied ist der Wert perfekter Preiskenntnis.' : ''}
              {reserve ? ' Regelenergie rechnet der Optimierer „Spot + Regelenergie“.' : ''}
            </Note>
          )}
          <div className="kpi-row">
            <Card label="Mehrerlös" value={`${signed(res?.uplift_eur)} €`} sub="am Tag ggü. Dauerbetrieb" accent="green" />
            <Card label="Netto inkl. EEG" value={`${fmt(res?.net_eeg_eur ?? res?.net_eur)} €`} sub={res?.eeg_premium_eur != null ? `Marktprämie ${fmt(res.eeg_premium_eur)} €, nach Gas` : 'nach Gas, ohne EEG'} />
            <Card label="BHKW-Laufzeit" value={`${fmt(res?.bhkw_h, 1)} h`} sub={starts(res?.starts)} />
            <Card label="Wasserstoff" value={`${fmt(res?.h2_mwh, 2)} MWh`} sub={res && res.carbon_t > 0 ? `${fmt(res.carbon_t, 2)} t Kohlenstoff` : `${fmt(res?.h2_eur)} € Wert`} accent="blue" />
          </div>

          {scen.length > 0 && (
            <Section title="Szenarien im Vergleich" right={<button className="btn" onClick={() => setScen([])}>Alle löschen</button>}>
              <div style={{ overflowX: 'auto' }}>
                <table className="nowrap">
                  <thead><tr><th>Szenario</th><th>Gas</th><th>H₂</th><th>CO₂</th><th>Technik</th><th>Optimierer</th><th>Mehrerlös</th><th>Netto inkl. EEG</th><th>Laufzeit</th><th /></tr></thead>
                  <tbody>{scen.map((s) => (
                    <tr key={s.id} style={shownNet(s.r) === best ? { background: 'var(--brand-soft)' } : undefined}>
                      <td><strong>{s.name}</strong>{shownNet(s.r) === best && scen.length > 1 ? ' ★' : ''}</td>
                      <td>{s.p.gas}</td><td>{IGNORES_PTX(s.p.algo) ? '—' : s.p.h2}</td><td>{IGNORES_PTX(s.p.algo) ? '—' : s.p.co2}</td><td>{techLabel(s.p)}</td><td>{algoLabel(s.p.algo)}</td>
                      <td style={{ fontWeight: 700, color: 'var(--c-pos)' }}>{signed(s.r.uplift_eur)} €</td>
                      <td style={{ fontWeight: 600 }}>{fmt(netOf(s.r))} €</td><td>{fmt(s.r.bhkw_h, 1)} h</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <button className="btn" onClick={() => setP(s.p)}>Laden</button>{' '}
                        <button className="btn" aria-label={`${s.name} entfernen`} onClick={() => setScen((x) => x.filter((y) => y.id !== s.id))}>×</button>
                      </td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </Section>
          )}

          <Section title="Erlös-Aufschlüsselung">
            {breakdown.map((b) => (
              <div key={b.label} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                <div style={{ width: 140, fontSize: 13 }}>{b.label}</div>
                <div style={{ flex: 1, height: 18, background: 'var(--fld-soft)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${(Math.abs(b.v) / scale) * 100}%`, background: b.v >= 0 ? 'var(--c-pos)' : 'var(--c-neg)' }} />
                </div>
                <div style={{ width: 90, textAlign: 'right', fontSize: 13, fontWeight: 600, color: b.v >= 0 ? 'var(--c-pos)' : 'var(--c-neg)' }}>{fmt(b.v)} €</div>
              </div>
            ))}
            <div style={{ fontSize: 12, color: 'var(--fld-faint)', marginTop: 8 }}>
              Die Gasmenge pro Tag ist fest — der Mehrerlös gegenüber Dauerbetrieb hängt deshalb nicht vom Gaspreis ab, der Netto-Erlös schon.
              {res?.praemie_eur_mwh != null && <> Marktprämie: anzulegender Wert minus Monatsmarktwert {fmt(res.marktwert_eur_mwh, 1)} € = {fmt(res.praemie_eur_mwh, 1)} €/MWh für {fmt(res.praemie_mwh, 1)} MWh
                (Jahresmenge mit Prämie, im Tagesmittel; keine Prämie bei negativen Preisen). Werte je Anlage unter Anlagendaten.</>}
            </div>
          </Section>

          <Section title="Fahrplan (neu optimiert)">
            <div style={{ height: 300 }}>
              {chart ? <Line data={chart} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { ticks: { maxTicksLimit: 12 } }, y: { title: { display: true, text: 'MW' } } } }} />
                : <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--fld-faint)' }}>rechnet …</div>}
            </div>
          </Section>
        </div>
      </div>
    </PageShell>
  )
}
