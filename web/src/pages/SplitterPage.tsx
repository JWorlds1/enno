// Splitter: je Viertelstunde Gas → Strom oder → H₂ + fester Kohlenstoff, mit dem Preisrechner (fairer Wert aus freien Marktdaten).
import { useState } from 'react'
import { Bar, Chart, Line } from 'react-chartjs-2'
import { fldApi, type CarbonPath, type PriceCheck } from '@/lib/api'
import { Card, CardGrid, ChartBox, ErrorBanner, Note, PageShell, Section, Segmented, Skeleton, dayWord, fmt, signed, useApi, useDebounced } from '@/ui'

const PATHS: { value: CarbonPath; label: string }[] = [
  { value: 'co2', label: 'CO₂-Wert' }, { value: 'cdr', label: 'Entnahme-Zertifikat' }, { value: 'black', label: 'Industrieruß' },
]
const PATH_SUB: Record<CarbonPath, string> = {
  co2: 'Kohlenstoff mit EU-CO₂-Preis bewertet (untere Grenze)',
  cdr: 'Kohlenstoff als CO₂-Entnahme-Zertifikat',
  black: 'Kohlenstoff als Produkt (Industrieruß, aus Ölpreis)',
}

/** Prüfergebnis gegen öffentliche Referenzpreise: Status, Abweichungen, Quellen mit Link. */
function CheckCell({ check }: { check?: PriceCheck | null }) {
  if (!check) return <>—</>
  const devs = check.refs.filter((r) => r.deviation_pct != null)
  const head = check.status === 'nachjustiert' ? `nachjustiert × ${fmt(check.factor, 2)}` : check.status
  if (!check.refs.length) return <>{head}</>
  return (
    <details>
      <summary>{head}{devs.length ? ` (${devs.map((r) => `${signed(r.deviation_pct, 0)} %`).join(', ')})` : ''}</summary>
      <ul style={{ margin: '6px 0 0 16px', fontSize: 12 }}>
        {check.refs.map((r) => <li key={r.date + r.source}>
          <a href={r.url} target="_blank" rel="noreferrer">{r.source}</a>: {r.ref_eur_kg == null ? 'keine Marktdaten am Tag' : `${fmt(r.ref_eur_kg, 2)} €/kg, Formel ${fmt(r.formula_eur_kg, 2)} €/kg`}
          {r.comparable ? '' : ` — ${r.note ?? 'nur zur Einordnung'}`}</li>)}
      </ul>
    </details>
  )
}

/** Eingabe „5,2“ oder „5.2“ → Zahl; leer oder ungültig → undefined (dann rechnet der Preisrechner). */
const num = (s: string): number | undefined => {
  const v = Number(s.replace(',', '.'))
  return s.trim() !== '' && isFinite(v) && v >= 0 ? v : undefined
}

export function SplitterPage() {
  const [carbon, setCarbon] = useState<CarbonPath>('co2')
  const [h2In, setH2In] = useState('')
  const [cIn, setCIn] = useState('')
  const own = useDebounced({ h2: num(h2In), c: num(cIn) }, 400)
  const prices = useApi(() => fldApi.valuePrices(), [])
  const noBlack = carbon === 'black' && prices.data?.carbon.black.eur_kg == null && own.c == null
  const split = useApi(() => (noBlack ? Promise.resolve(null) : fldApi.splitter({ carbon, h2: own.h2 && own.h2 > 0 ? own.h2 : undefined, c: own.c })),
    [carbon, own, noBlack])
  const d = split.data
  const ownQ = { carbon, h2: own.h2 && own.h2 > 0 ? own.h2 : undefined, c: own.c }
  const plan = useApi(() => (noBlack ? Promise.resolve(null) : fldApi.splitterPlan(ownQ)), [carbon, own, noBlack])
  const year = useApi(() => (carbon === 'black' && prices.data?.carbon.black.eur_kg == null ? Promise.resolve(null) : fldApi.splitterYear(carbon)),
    [carbon, prices.data])
  const y = year.data
  const curve = useApi(() => fldApi.valueCurve(), [])
  const proof = useApi(() => (carbon === 'black' && prices.data?.carbon.black.eur_kg == null ? Promise.resolve(null) : fldApi.splitterProof(carbon)),
    [carbon, prices.data])
  const pf = proof.data
  const csvHref = `/fld-api/splitter-bids.csv?carbon=${carbon}${ownQ.h2 != null ? `&h2=${ownQ.h2}` : ''}${ownQ.c != null ? `&c=${ownQ.c}` : ''}`
  const best = d && (d.revenue.nur_strom >= d.revenue.nur_plasma ? 'nur Strom' : 'nur H₂ + Kohlenstoff')
  const n = d?.slots.length ?? 96

  const chart = d && {
    labels: d.slots.map((s) => s.time),
    datasets: [
      { type: 'bar' as const, label: 'Strom (BHKW)', data: d.slots.map((s) => (s.route === 'strom' ? s.price : null)), backgroundColor: 'var(--c-price)', stack: 'p' },
      { type: 'bar' as const, label: 'H₂ + Kohlenstoff (Plasma)', data: d.slots.map((s) => (s.route === 'plasma' ? s.price : null)), backgroundColor: 'var(--c-plasma)', stack: 'p' },
      { type: 'line' as const, label: 'Schwelle', data: d.slots.map(() => d.threshold_eur_mwh), borderColor: 'var(--c-neg)', borderDash: [6, 4], borderWidth: 2, pointRadius: 0, backgroundColor: 'transparent' },
    ],
  }

  return (
    <PageShell title="Splitter: Strom oder H₂ + Kohlenstoff"
      subtitle="Je Viertelstunde geht das Gas dorthin, wo es mehr bringt: ins BHKW (Strom) oder in die Plasma-Pyrolyse (Wasserstoff + fester Kohlenstoff). H₂- und Kohlenstoffwert rechnet der Preisrechner aus frei verfügbaren Marktdaten — oder Sie tragen eigene Preise ein."
      actions={<div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <Segmented value={carbon} onChange={setCarbon} options={PATHS} />
        {!noBlack && <a className="btn" href={csvHref} download>Gebote herunterladen (CSV)</a>}
      </div>}>
      <ErrorBanner error={prices.error ?? split.error ?? plan.error ?? year.error ?? proof.error} />

      <Section title="Preisrechner">
        {prices.loading || !prices.data ? <Skeleton /> : <>
          <table>
            <thead><tr><th>Produkt</th><th>Wert</th><th>Rechnung</th><th>Quelle</th><th>Prüfung</th></tr></thead>
            <tbody>
              <tr><td>Wasserstoff (grauer H₂ als Vergleich)</td><td className="num">{fmt(prices.data.h2.eur_kg, 2)} €/kg</td><td>{prices.data.h2.formula}</td><td>{prices.data.h2.source}</td><td><CheckCell check={prices.data.h2.check} /></td></tr>
              {PATHS.map((p) => {
                const it = prices.data!.carbon[p.value]
                return <tr key={p.value} aria-current={p.value === carbon ? 'true' : undefined} style={p.value === carbon ? { fontWeight: 600 } : undefined}>
                  <td>Kohlenstoff: {p.label}</td><td className="num">{it.eur_kg == null ? 'keine Daten' : `${fmt(it.eur_kg, 2)} €/kg`}</td><td>{it.formula}</td><td>{it.source}</td><td><CheckCell check={it.check} /></td></tr>
              })}
            </tbody>
          </table>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 14, alignItems: 'end' }}>
            <label style={{ display: 'grid', gap: 4, fontSize: 13 }}>Eigener H₂-Preis (€/kg)
              <input value={h2In} onChange={(e) => setH2In(e.target.value)} placeholder={fmt(prices.data.h2.eur_kg, 2)} inputMode="decimal" style={{ width: 130, padding: '5px 8px' }} /></label>
            <label style={{ display: 'grid', gap: 4, fontSize: 13 }}>Eigener Kohlenstoffpreis (€/kg)
              <input value={cIn} onChange={(e) => setCIn(e.target.value)} placeholder={fmt(prices.data.carbon[carbon].eur_kg, 2)} inputMode="decimal" style={{ width: 130, padding: '5px 8px' }} /></label>
            {(h2In || cIn) && <button type="button" className="btn" onClick={() => { setH2In(''); setCIn('') }}>Preisrechner verwenden</button>}
          </div>
          <p style={{ fontSize: 12, color: 'var(--fld-faint)', marginTop: 8 }}>Marktdaten vom {prices.data.as_of}. Fairer Wert nach dem Ersatzkostenprinzip, kein erzielter Preis — Vertrags- oder Angebotspreise von FLD oben eintragen.</p>
        </>}
      </Section>

      {noBlack && <Note tone="warn" title="Keine Öldaten">Für Industrieruß fehlen Öl- oder Wechselkursdaten. Statt zu schätzen: eigenen Kohlenstoffpreis eintragen oder andere Verwertung wählen.</Note>}

      <CardGrid>
        {split.loading || !d ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} />) : <>
          <Card label="Strom lohnt ab" value={`${fmt(d.threshold_eur_mwh)} €/MWh`} sub={`H₂ ${fmt(d.h2_eur_kg, 2)} €/kg · C ${fmt(d.c_eur_kg, 2)} €/kg${d.own_prices ? ' (eigene Preise)' : ''}`} accent="red" />
          <Card label="Strom-Viertelstunden" value={`${d.strom_slots} von ${n}`} sub={`${dayWord(d.target_day)}, ${d.price_basis === 'Auktion' ? 'Auktionspreise' : 'Preisprognose'}`} />
          <Card label="Erlös Splitter" value={`${fmt(d.revenue.splitter)} €`} sub="je Gaseinheit und Viertelstunde, Tagessumme" accent="amber" />
          <Card label="Mehr als Einzelweg" value={`${signed(d.uplift_vs_best)} €`} sub={`gegenüber ${best}`} accent={d.uplift_vs_best > 0 ? 'green' : 'none'} />
        </>}
      </CardGrid>

      {d && <CardGrid>
        <Card label="Umschaltungen" value={`${d.switches}`} sub={d.block_slots > 0 ? 'Ergebnis der Blockgebote (Auktion)' : `nur bei ±${fmt(d.margin_eur_mwh)} €/MWh Abstand zur Schwelle (Prognosefehler)`} />
        <Card label="BHKW-Mindestlaufzeit" value={`${fmt(d.min_run_slots / 4, 2)} h`} sub="kürzere Strom-Läufe gehen ins Plasma" />
        <Card label="Unsicher" value={`${d.unsure_slots} von ${n}`} sub={d.price_basis === 'Auktion' ? 'Preise stehen fest' : 'Prognoseband P10–P90 kreuzt die Schwelle'} accent={d.unsure_slots > n * 0.2 ? 'red' : 'none'} />
      </CardGrid>}

      <Section title={`Weg je Viertelstunde (${PATH_SUB[carbon]})`}>
        <ChartBox height={340}>
          {chart ? <Chart type="bar" data={chart} options={{ responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            scales: { x: { stacked: true, ticks: { maxTicksLimit: 12 } }, y: { title: { display: true, text: '€/MWh' } } }, plugins: { legend: { position: 'bottom' } } }} />
            : <Skeleton height="100%" />}
        </ChartBox>
      </Section>

      {d && <Section title="Erlös je Gaseinheit">
        <table>
          <thead><tr><th>Betrieb</th><th>Erlös am Tag</th><th>Verhältnis aus derselben Gasmenge</th></tr></thead>
          <tbody>
            <tr><td>Splitter</td><td className="num">{fmt(d.revenue.splitter)} €</td><td>je Viertelstunde der bessere Weg</td></tr>
            <tr><td>Nur Strom</td><td className="num">{fmt(d.revenue.nur_strom)} €</td><td>{fmt(d.ratio.el_kwh)} kWh Strom</td></tr>
            <tr><td>Nur H₂ + Kohlenstoff</td><td className="num">{fmt(d.revenue.nur_plasma)} €</td><td>{fmt(d.ratio.h2_kg, 1)} kg H₂ + {fmt(d.ratio.c_kg, 1)} kg C</td></tr>
          </tbody>
        </table>
      </Section>}

      <Section title="Mit Anlagengrenzen (Optimierer: Gasspeicher, Tagesgas, Starts, Mindestlaufzeit, Wärme)">
        {plan.loading || !plan.data ? <Skeleton /> : <>
          <CardGrid>
            <Card label="Plus ggü. nur Strom" value={`${signed(plan.data.uplift_eur)} €`} sub={`am Liefertag, ${plan.data.price_basis === 'Auktion' ? 'Auktionspreise' : 'Prognose'}`} accent={plan.data.uplift_eur > 0 ? 'green' : 'none'} />
            <Card label="Gas ins Plasma" value={`${fmt(plan.data.plasma_gas_mwh, 1)} MWh`} sub={`${fmt(plan.data.h2_kg)} kg H₂ + ${fmt(plan.data.c_kg)} kg Kohlenstoff`} accent="amber" />
            <Card label="BHKW" value={`${fmt(plan.data.bhkw_h, 2)} h`} sub={`${plan.data.starts} ${plan.data.starts === 1 ? 'Start' : 'Starts'}`} />
          </CardGrid>
          <ChartBox height={260} style={{ marginTop: 14 }}>
            <Line data={{ labels: plan.data.times, datasets: [
              { label: 'BHKW MW', data: plan.data.bhkw_mw, borderColor: 'var(--c-price)', backgroundColor: 'transparent', pointRadius: 0, stepped: true },
              { label: 'Gas ins Plasma MW', data: plan.data.plasma_gas_mw, borderColor: 'var(--c-plasma)', backgroundColor: 'transparent', pointRadius: 0, stepped: true },
            ] }} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { ticks: { maxTicksLimit: 12 } }, y: { title: { display: true, text: 'MW' } } } }} />
          </ChartBox>
          <p style={{ fontSize: 12, color: 'var(--fld-faint)', marginTop: 8 }}>Hier ist das Tagesgas begrenzt: Plasma konkurriert mit den besten BHKW-Stunden, nicht mit dem Tagesdurchschnitt. Modell-Anlage aus den Anlagendaten.</p>
        </>}
      </Section>

      <Section title="Tagesnachweis: jeder ausgegebene Plan, abgerechnet auf echten Preisen">
        {proof.loading || !pf ? <Skeleton /> : <>
          <CardGrid>
            <Card label="Tage in Folge" value={`${pf.summary.streak_days}`} sub={pf.summary.last_settled ? `lückenlos bis ${pf.summary.last_settled}` : 'noch kein Tag abgerechnet'} accent={pf.summary.streak_days >= 7 ? 'green' : 'amber'} />
            <Card label="Abgerechnet" value={`${pf.summary.settled_days} Tage`} sub={`davon ${pf.summary.forecast_days} vor der Auktion geplant`} />
            <Card label="Lücken" value={`${pf.summary.missing_days + pf.summary.late_days}`} sub={`${pf.summary.missing_days} ohne Plan, ${pf.summary.late_days} zu spät`} accent={pf.summary.missing_days + pf.summary.late_days > 0 ? 'red' : 'none'} />
            <Card label="Erreicht" value={`${fmt(pf.summary.capture_pct, 1)} %`} sub={`${signed(pf.summary.plus_vs_best_eur)} € mehr als der beste Einzelweg`} accent="amber" />
          </CardGrid>
          <div style={{ overflowX: 'auto', marginTop: 14 }}>
            <table>
              <thead><tr><th>Liefertag</th><th>Status</th><th>Ausgegeben</th><th>Plan</th><th>Bester Einzelweg</th><th>Gebote</th><th>Bestmöglich</th><th>Erreicht</th><th>Richtig</th></tr></thead>
              <tbody>{[...pf.days].reverse().map((x) => <tr key={x.day}>
                <td>{x.day}</td>
                <td>{x.status}{x.basis === 'Auktion' && x.status === 'abgerechnet' ? ' (nach der Auktion)' : ''}</td>
                <td>{x.issued ? x.issued.slice(0, 16).replace('T', ' ') + ' UTC' : '—'}</td>
                <td className="num">{x.revenue ? `${fmt(x.revenue.plan)} €` : '—'}</td>
                <td className="num">{x.revenue ? `${fmt(Math.max(x.revenue.nur_strom, x.revenue.nur_plasma))} €` : '—'}</td>
                <td className="num">{x.revenue ? `${fmt(x.revenue.gebote)} €` : '—'}</td>
                <td className="num">{x.revenue ? `${fmt(x.revenue.ideal)} €` : '—'}</td>
                <td className="num">{x.capture_pct != null ? `${fmt(x.capture_pct, 1)} %` : '—'}</td>
                <td className="num">{x.correct_pct != null ? `${fmt(x.correct_pct)} %` : '—'}</td>
              </tr>)}</tbody>
            </table>
          </div>
          <Note tone={pf.summary.missing_days + pf.summary.late_days > 0 ? 'warn' : 'pos'} title="So ist der Nachweis gerechnet">
            {'Je Liefertag der zuerst ausgegebene Plan aus der Datenbank, so wie er damals rausging — kein Backtest. Abgerechnet zu den Day-Ahead-Preisen der Börse, je Gaseinheit und Viertelstunde. '}
            {'„Gebote“: was die Blockgebote mit Mindestpreis gebracht hätten. „Nach der Auktion“: der Lauf kam erst nach der Auktion, die Preise standen schon fest. '}
            {pf.summary.missing_days + pf.summary.late_days > 0 && 'Lücken heißen: an diesem Tag hat das System keinen rechtzeitigen Plan geliefert.'}
          </Note>
        </>}
      </Section>

      <Section title="Nachrechnung: ein Jahr Splitter auf echten Preisen">
        {year.loading || !y ? <Skeleton /> : <>
          <CardGrid>
            <Card label="Umschaltungen/Jahr" value={fmt(y.switches_per_year)} sub={`${fmt(y.switches_per_day, 1)} pro Tag, Ø BHKW-Lauf ${fmt(y.avg_run_h, 1)} h, ${fmt(y.short_runs_per_year)} kürzer als ${fmt(y.min_run_h, 2)} h`} />
            <Card label="BHKW-Anteil" value={`${fmt(y.bhkw_share_pct)} %`} sub={`Plasma ${fmt(100 - y.bhkw_share_pct)} % der Viertelstunden`} />
            <Card label="Jahres-Plus" value={`${signed(y.uplift_vs_best_pct, 1)} %`} sub={`${fmt(y.per_year.splitter / 1000)} T€ statt ${fmt(Math.max(y.per_year.nur_strom, y.per_year.nur_plasma) / 1000)} T€ im Jahr (je MW Dauerbetrieb)`} accent={y.uplift_vs_best_pct > 0 ? 'green' : 'none'} />
            <Card label="Vom Bestmöglichen" value={`${fmt(y.bids.capture_pct, 1)} %`} sub={`mit Blockgeboten; Plan auf Prognose ${fmt(y.capture_pct, 1)} %`} accent="amber" />
          </CardGrid>
          <ChartBox height={240} style={{ marginTop: 14 }}>
            <Bar data={{ labels: y.hourly_bhkw_pct.map((_, h) => `${String(h).padStart(2, '0')} Uhr`), datasets: [
              { label: 'BHKW-Anteil je Stunde (%)', data: y.hourly_bhkw_pct, backgroundColor: 'var(--c-price)' },
            ] }} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { y: { min: 0, max: 100, title: { display: true, text: '% BHKW' } } } }} />
          </ChartBox>
          <table style={{ marginTop: 14 }}>
            <thead><tr><th>Monat</th><th>BHKW-Anteil</th><th>Mehr als bester Einzelweg</th></tr></thead>
            <tbody>{y.monthly.map((m) => <tr key={m.month}><td>{m.month}</td><td className="num">{fmt(m.bhkw_pct)} %</td><td className="num">{signed(m.uplift_eur)} €</td></tr>)}</tbody>
          </table>
          <Note tone={y.uplift_vs_best_pct > 0 ? 'pos' : 'warn'} title="Ergebnis der Nachrechnung">
            {`${y.days} Tage (${y.from} – ${y.to}), geplant auf der damaligen Prognose mit ±${fmt(y.margin_eur_mwh)} €/MWh Abstand, abgerechnet zu Ist-Preisen. `}
            {`Blockgebote mit Mindestpreis treffen ${fmt(y.bids.correct_pct)} % der Viertelstunden richtig (${fmt(y.bids.switches_per_year)} Umschaltungen/Jahr). `}
            {y.milp.days > 0 && `Mit Anlagengrenzen (letzte ${y.milp.days} Tage): ${signed(y.milp.uplift_eur_per_day)} €/Tag gegenüber nur Strom, ${fmt(y.milp.plasma_gas_mwh_per_day, 1)} MWh Gas ins Plasma pro Tag.`}
            {y.uplift_vs_best_pct <= 0 && ' Der Splitter bringt in diesem Zeitraum nichts gegenüber dem besten Einzelweg — so nicht in Betrieb nehmen.'}
          </Note>
        </>}
      </Section>

      <Section title="Preiskurve: die nächsten 12 Monate aus Terminpreisen">
        {curve.loading || !curve.data ? <Skeleton /> : <>
          <ChartBox height={240}>
            <Line data={{ labels: curve.data.months.map((m) => m.month), datasets: [
              { label: 'Strom lohnt ab (€/MWh)', data: curve.data.months.map((m) => m.threshold[carbon]), borderColor: 'var(--c-neg)', backgroundColor: 'transparent', spanGaps: false },
            ] }} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { y: { title: { display: true, text: '€/MWh' } } } }} />
          </ChartBox>
          <table style={{ marginTop: 14 }}>
            <thead><tr><th>Liefermonat</th><th>Gas TTF €/MWh</th><th>Brent $/bbl</th><th>H₂ €/kg</th><th>Kohlenstoff €/kg</th><th>Strom lohnt ab</th></tr></thead>
            <tbody>{curve.data.months.map((m) => {
              const ip = (k: string) => (m.interpolated.includes(k) ? ' (interpoliert)' : '')
              return <tr key={m.month}><td>{m.month}</td>
                <td className="num">{m.ttf_eur_mwh == null ? 'keine Daten' : `${fmt(m.ttf_eur_mwh, 2)}${ip('ttf_eur_mwh')}`}</td>
                <td className="num">{m.brent_usd_bbl == null ? 'keine Daten' : `${fmt(m.brent_usd_bbl, 2)}${ip('brent_usd_bbl')}`}</td>
                <td className="num">{fmt(m.h2, 2)}</td><td className="num">{fmt(m.carbon[carbon], 2)}</td>
                <td className="num">{m.threshold[carbon] == null ? '—' : `${fmt(m.threshold[carbon])} €/MWh`}</td></tr>
            })}</tbody>
          </table>
          <p style={{ fontSize: 12, color: 'var(--fld-faint)', marginTop: 8 }}>{`Terminpreise Gas und Öl (Yahoo), CO₂ ${fmt(curve.data.eua_eur_t, 2)} €/t und Wechselkurs auf dem Stand vom ${curve.data.as_of} gehalten — dafür gibt es keine freien Monatspreise. Lücken zwischen gelisteten Monaten linear verbunden, danach keine Verlängerung.`}</p>
        </>}
      </Section>

      {d && <Note tone={d.uplift_vs_best > 0 ? 'pos' : 'info'} title="Befund">
        {d.strom_slots === 0 || d.strom_slots === n
          ? `Heute bringt Umschalten nichts: ${best} ist in jeder Viertelstunde besser.`
          : `Strom in ${d.blocks.join(', ')}, sonst H₂ + Kohlenstoff. Das bringt ${signed(d.uplift_vs_best)} € mehr als ${best}.`}
        {' '}Ohne Gasspeicher und Wärme — die rechnet der Abschnitt „Mit Anlagengrenzen“.
      </Note>}
    </PageShell>
  )
}
