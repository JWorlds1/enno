// Anlagendaten — FLD-Anlagenwerte importieren (JSON oder CSV „parameter,wert“), prüfen, speichern.
import { useEffect, useState, type ChangeEvent, type DragEvent } from 'react'
import { fldApi, type PlantConfigData } from '@/lib/api'
import { ErrorBanner, Note, PageShell, Section, Skeleton, fmt } from '@/ui'

const ACCEPT = '.json,.csv,.txt'

const LABELS: Record<string, string> = {
  p_bhkw_mw: 'BHKW-Leistung (MWel)', eta_el: 'Elektrischer Wirkungsgrad', min_load: 'Mindestlast (Anteil)',
  start_cost_eur: 'Startkosten (€)', full_hours_per_day: 'Gasbudget (Volllast-h/Tag)', storage_hours: 'Gasspeicher (Volllast-h)',
  heat_min_runtime_slots: 'Wärme-Mindestlauf (¼-h-Slots)', heat_credit_eur_mwh: 'Wärmegutschrift (€/MWh)',
  p_el_mw: 'Elektrolyseur (MWel)', eta_ptx: 'PtX-Wirkungsgrad', h2_value_eur_mwh: 'H₂-Wert (€/MWh)', ptx_opex_eur_mwh: 'PtX-Opex (€/MWh)',
  min_up_slots: 'Mindestlaufzeit (¼-h-Slots)', min_down_slots: 'Mindeststillstand (¼-h-Slots)',
  split_el_kwh: 'Splitter: kWh Strom je Gaseinheit', split_h2_kg: 'Splitter: kg H₂ je Gaseinheit', split_c_kg: 'Splitter: kg C je Gaseinheit', split_plasma_kwh: 'Splitter: Plasma-Strom kWh je Gaseinheit',
  eta_pyro_h2: 'Pyrolyse: H₂ je MWh Gas', plasma_el_per_gas: 'Pyrolyse: Strom je MWh Gas', carbon_t_per_gas: 'Pyrolyse: t C je MWh Gas',
  pyro_max_gas_mwh: 'Pyrolyse: max. Gas je Slot (MWh)',
  bio_premium_eur_mwh: 'Biomethan-Aufschlag (€/MWh)', aw_eur_mwh: 'EEG: anzulegender Wert (€/MWh)',
  eeg_share: 'EEG: Anteil Leistung mit Prämie (Jahresmenge)', flex_eur_kw_a: 'EEG: Flexibilitätszuschlag (€/kW·a)', grid_co2_max_t_mwh: 'Netz-CO₂ ohne EE (t/MWh)', dt_h: 'Zeitschritt (h)', slots_per_day: 'Slots pro Tag',
}

function parseFile(text: string): Record<string, number> {
  const t = text.trim()
  if (t.startsWith('{')) {
    const obj = JSON.parse(t)
    return Object.fromEntries(Object.entries(obj.params ?? obj).map(([k, v]) => [k, Number(v)]))
  }
  const out: Record<string, number> = {}
  for (const line of t.split(/\r?\n/)) {
    // „parameter;0,65“ (deutsch) oder „parameter,0.65“ — das Komma trennt nur, wenn kein ; oder Tab vorkommt.
    const sep = line.includes(';') ? ';' : line.includes('\t') ? '\t' : ','
    const i = line.indexOf(sep)
    if (i < 0) continue
    const k = line.slice(0, i).trim()
    const v = line.slice(i + 1).trim().replace(',', '.')
    if (k && v !== '' && !isNaN(Number(v))) out[k] = Number(v)
  }
  return out
}

export function PlantConfigPage() {
  const [cfg, setCfg] = useState<PlantConfigData | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)      // Laden fehlgeschlagen
  const [problem, setProblem] = useState<string | null>(null)  // Import/Speichern abgelehnt
  const [msg, setMsg] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    fldApi.plantConfig().then((c) => {
      setCfg(c)
      setDraft(Object.fromEntries(Object.entries(c.override).map(([k, v]) => [k, String(v)])))
    }).catch((e) => setError(String(e.message ?? e)))
  }, [])

  async function importFile(f: File) {
    setProblem(null)
    try {
      const parsed = parseFile(await f.text())
      if (!Object.keys(parsed).length) throw new Error('keine Zeile „parameter,wert“ gefunden')
      setDraft((d) => ({ ...d, ...Object.fromEntries(Object.entries(parsed).map(([k, v]) => [k, String(v)])) }))
      setMsg(`${Object.keys(parsed).length} Werte aus ${f.name} übernommen, noch nicht gespeichert.`)
    } catch (err) {
      setMsg(null)
      setProblem(`Datei nicht lesbar (${f.name}): ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (f) void importFile(f)
    e.target.value = ''  // dieselbe Datei erneut wählbar
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files?.[0]
    if (f) void importFile(f)
  }

  async function save() {
    setProblem(null)
    const params = Object.fromEntries(Object.entries(draft).filter(([, v]) => v.trim() !== '').map(([k, v]) => [k, Number(v.replace(',', '.'))]))
    try {
      const c = await fldApi.setPlantConfig(params)
      setCfg(c)
      setMsg(`Gespeichert: ${Object.keys(c.override).length} Anlagenwerte, ${Object.keys(c.diff).length} weichen vom Modell ab.`)
    } catch (err) {
      setMsg(null)
      setProblem(`Nicht gespeichert: ${err instanceof Error ? err.message.replace(/^\/plant-config → \d+: /, '') : String(err)}`)
    }
  }

  return (
    <PageShell title="Anlagendaten" subtitle="Hier kommen die realen FLD-Anlagenwerte hinein: Leistung, Wirkungsgrade, Speicher, Kosten. Die Werte werden geprüft und je Mandant gespeichert."
      actions={<div style={{ display: 'flex', gap: 8 }}>
        <label className="btn">Datei importieren<input type="file" accept={ACCEPT} onChange={onFile} style={{ display: 'none' }} /></label>
        <button className="btn btn-primary" onClick={save} disabled={!cfg}>Speichern</button>
      </div>}>
      <ErrorBanner error={error} />
      {problem && <Note tone="warn" alert>{problem}</Note>}
      {msg && <Note tone="pos">{msg}</Note>}
      <div className={`dropzone${dragging ? ' active' : ''}`}
        onDragEnter={(e) => { e.preventDefault(); setDragging(true) }}
        onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}>
        <strong>Datei hierher ziehen</strong> oder oben „Datei importieren“ — JSON oder CSV (parameter,wert)
      </div>
      {cfg?.applied_to_optimizer && (
        <Note title="So wirken die Werte">Gespeicherte Werte gelten sofort für alle Live-Berechnungen: Was-wäre-wenn, Sensitivität, Risiko,
          Erlös ↔ CO₂, Erlös-Stapel, Plasma, Speicher, CDR-Preis und Enno. Cockpit, Fahrplan und Backtest zeigen den letzten Tageslauf
          und übernehmen die Werte mit dem nächsten Lauf. Der Server prüft vor dem Speichern, ob die Anlage so betreibbar ist.</Note>
      )}
      <Section title="Parameter">
        {!cfg ? <Skeleton height={400} /> : (
          <table>
            <thead><tr><th>Parameter</th><th>Modell</th><th>Anlage (FLD)</th><th>Abweichung</th></tr></thead>
            <tbody>{Object.entries(cfg.defaults).map(([k, def]) => {
              const v = draft[k] ?? ''
              const n = Number(v.replace(',', '.'))
              const dev = v.trim() !== '' && isFinite(n) && def !== 0 ? ((n - def) / def) * 100 : null
              return (
                <tr key={k}>
                  <td>{LABELS[k] ?? k}<div style={{ fontSize: 11, color: 'var(--fld-faint)' }}>{k}</div></td>
                  <td>{fmt(def, 3)}</td>
                  <td>{cfg.fixed.includes(k)
                    ? <span style={{ color: 'var(--fld-faint)', fontSize: 12 }}>fest (Zeitraster)</span>
                    : <input value={v} placeholder="—" inputMode="decimal" aria-label={LABELS[k] ?? k} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} style={{ width: 110, padding: '5px 8px' }} />}</td>
                  <td style={{ color: dev == null || Math.abs(dev) < 0.5 ? 'var(--fld-faint)' : 'var(--brand-strong)', fontWeight: 600 }}>{dev == null ? '—' : `${dev > 0 ? '+' : ''}${fmt(dev, 1)} %`}</td>
                </tr>
              )
            })}</tbody>
          </table>
        )}
      </Section>
      <Note>Importformat: JSON <code>{'{"eta_el": 0.40}'}</code> oder CSV mit Zeilen <code>parameter,wert</code>. Unbekannte Parameter und negative Werte lehnt der Server ab.</Note>
    </PageShell>
  )
}
