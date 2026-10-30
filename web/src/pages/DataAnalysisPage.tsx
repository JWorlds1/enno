// Datenanalyse — EDA-Explorer als Story: Grafiken nach Thema gruppiert, jede mit Insight-Untertitel.
import { useEffect, useState } from 'react'
import { fldApi, figureUrl, type FigureItem } from '@/lib/api'
import { PageShell, ErrorBanner, Section } from '@/ui'
import { PriceHeatmap } from '@/components/PriceHeatmap'

// Kuratierte Story: Thema → Grafiken mit Insight. Unbekannte landen unter „Weitere".
const GROUPS: { title: string; note: string; figs: { name: string; caption: string }[] }[] = [
  {
    title: 'Preisverhalten', note: 'Warum sich Flexibilität überhaupt lohnt.',
    figs: [
      { name: 'A_preis.png', caption: 'Strompreis-Verlauf — hohe Tages-Volatilität = das Flex-Potenzial, das die Optimierung hebt.' },
      { name: 'eda_distribution.png', caption: 'Preisverteilung mit Fat Tails — extreme Preise treten häufiger auf als eine Normalverteilung erwarten ließe.' },
      { name: 'eda_negprice.png', caption: 'Negative Preise bei hohem EE-Anteil — Fenster für günstigen Strombezug (Elektrolyse).' },
      { name: 'C_negativ_vola.png', caption: 'Volatilität rund um Negativpreis-Phasen — die riskantesten, aber wertvollsten Stunden.' },
      { name: 'eda_intraday.png', caption: 'Intraday-Muster — teure Morgen- und Abendspitzen, in die das BHKW gebündelt wird.' },
      { name: 'eda_weekday.png', caption: 'Wochentag-Effekt — Werktage systematisch teurer als Wochenenden.' },
    ],
  },
  {
    title: 'Regime & Unsicherheit', note: 'Warum kalibrierte Unsicherheit (Conformal) nötig ist.',
    figs: [
      { name: 'eda_regime.png', caption: 'Regime-Shift — das Marktverhalten wechselt; statische Prognose-Intervalle versagen, daher Adaptive Conformal Inference.' },
      { name: 'eda_autocorr.png', caption: 'Autokorrelation — starke 24h-Periodik, Basis der Kalender-/Lag-Features.' },
      { name: 'eda_crosscorr.png', caption: 'Kreuzkorrelation Last/EE ↔ Preis — treibende Zusammenhänge über Zeitversätze.' },
    ],
  },
  {
    title: 'Treiber & Kausalität', note: 'Was den Preis wirklich bewegt — und was das Modell nutzt.',
    figs: [
      { name: 'B_treiber.png', caption: 'Preistreiber — die Residuallast (Last minus EE) dominiert den Spotpreis.' },
      { name: 'eda_drivers.png', caption: 'Treiber-Detail — Beitrag der einzelnen Fundamentalgrößen.' },
      { name: 'eda_causal.png', caption: 'Kausalkette — EE-Anteil → Residuallast → Preis; die physikalische Logik hinter dem Modell.' },
      { name: 'eda_shap.png', caption: 'SHAP (Vorstudien-Modell) — welche Features die Prognose am stärksten treiben (Erklärbarkeit).' },
      { name: 'eda_vif.png', caption: 'VIF — Multikollinearität der Features geprüft, um Scheinkorrelationen zu vermeiden.' },
      { name: 'eda_entsoe.png', caption: 'ENTSO-E D-1-Prognosen (Last/Wind/Solar) — heute nur zum Vergleich; das Modell nutzt Wetterprognosen (Open-Meteo) für Wind und Sonne.' },
    ],
  },
  {
    title: 'Modellgüte & Ergebnis (Vorstudie)', note: 'Stand Juni 2026. Den laufend nachgerechneten Nachweis zeigen die Seiten Backtest und Prognose-Güte.',
    figs: [
      { name: 'D_prognose_backtest.png', caption: 'Prognose vs. Ist, eine Woche im Juni 2026 (Vorstudie) — aktuelle Werte: Seite Backtest.' },
      { name: 'hero_timeline.png', caption: 'Hero-Timeline — der resultierende optimierte Fahrplan (Preis + Dispatch).' },
    ],
  },
]

export function DataAnalysisPage() {
  const [have, setHave] = useState<Set<string>>(new Set())
  const [extra, setExtra] = useState<FigureItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [zoom, setZoom] = useState<string | null>(null)

  useEffect(() => {
    fldApi.figures().then((figs) => {
      setHave(new Set(figs.map((f) => f.name)))
      const known = new Set(GROUPS.flatMap((g) => g.figs.map((f) => f.name)))
      setExtra(figs.filter((f) => !known.has(f.name)))
    }).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const Tile = ({ name, caption }: { name: string; caption: string }) => (
    <div style={{ background: 'var(--fld-card)', borderRadius: 12, border: '1px solid var(--fld-border)', overflow: 'hidden' }}>
      <img src={figureUrl(name)} alt={caption} onClick={() => setZoom(figureUrl(name))} style={{ width: '100%', display: 'block', background: 'var(--fld-bg)', cursor: 'zoom-in' }} loading="lazy" />
      <div style={{ padding: '12px 14px', fontSize: 12.5, color: 'var(--fld-text)', lineHeight: 1.5 }}>{caption}</div>
    </div>
  )

  return (
    <PageShell title="Datenanalyse" subtitle="Die explorative Analyse aus der Vorstudie (Daten bis Juni 2026), die zum heutigen Modell geführt hat. Aktuelle Zahlen: Backtest und Prognose-Güte.">
      <ErrorBanner error={error} />
      <Section title="Live: Preis-Heatmap — wann ist Strom teuer? (Ø nach Wochentag × Stunde)">
        <PriceHeatmap />
      </Section>
      {GROUPS.map((g) => {
        const figs = g.figs.filter((f) => have.has(f.name))
        if (!figs.length) return null
        return (
          <div key={g.title} style={{ marginBottom: 30 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 12 }}>
              <h2 style={{ fontSize: 19, fontWeight: 700 }}>{g.title}</h2>
              <span style={{ fontSize: 13, color: 'var(--fld-faint)' }}>{g.note}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 16 }}>
              {figs.map((f) => <Tile key={f.name} {...f} />)}
            </div>
          </div>
        )
      })}
      {extra.length > 0 && (
        <div style={{ marginBottom: 30 }}>
          <h2 style={{ fontSize: 19, fontWeight: 700, marginBottom: 12 }}>Weitere</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 16 }}>
            {extra.map((f) => <Tile key={f.name} name={f.name} caption={f.title} />)}
          </div>
        </div>
      )}
      {have.size === 0 && !error && <div style={{ color: 'var(--fld-faint)' }}>lädt…</div>}
      {zoom && (
        <div onClick={() => setZoom(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50, cursor: 'zoom-out', padding: 40 }}>
          <img src={zoom} alt="" style={{ maxWidth: '100%', maxHeight: '100%', borderRadius: 8 }} />
        </div>
      )}
    </PageShell>
  )
}
