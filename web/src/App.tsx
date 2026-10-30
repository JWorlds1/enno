// FLD OS Shell — linke Leiste mit zwei Reitern (Module | Enno), einklappbare Modulgruppen,
// Hash-Routing (deep-linkbar), Status, Hell/Dunkel.
import { lazy, Suspense, useEffect, useState, type ComponentType, type LazyExoticComponent } from 'react'
import { BRAND } from './brand'
import { applyChartTheme } from './chart-setup'
import { EnnoAvatar, EnnoPanel, type EnnoState } from './Enno'
import { Logo } from './Logo'
import { fldApi, type StatusData } from './lib/api'
import { Skeleton } from './ui'

const page = (load: () => Promise<Record<string, ComponentType>>, name: string): LazyExoticComponent<ComponentType> =>
  lazy(() => load().then((m) => ({ default: m[name] })))

interface Route { path: string; label: string; Component: LazyExoticComponent<ComponentType> }
interface Group { id: string; title: string; icon: string; routes: Route[] }

// Icon-Pfade (24er-Raster, Strich) — bewusst inline, keine Icon-Bibliothek.
const ICON = {
  betrieb: 'M12 14l4-4M4 18a8 8 0 1 1 16 0',
  planung: 'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4',
  erloese: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  prognose: 'M3 17l5-6 4 3 8-9M15 5h5v5',
  nachweis: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3zM8.5 12l2.5 2.5 4.5-5',
  anlage: 'M3 21V10l6 4V10l6 4V6l6 4v11H3z',
}

const NAV: Group[] = [
  { id: 'betrieb', title: 'Betrieb', icon: ICON.betrieb, routes: [
    { path: 'cockpit', label: 'Cockpit', Component: page(() => import('./pages/DashboardPage'), 'DashboardPage') },
    { path: 'empfehlung', label: 'Fahrplan', Component: page(() => import('./pages/EmpfehlungPage'), 'EmpfehlungPage') },
  ] },
  { id: 'planung', title: 'Planung', icon: ICON.planung, routes: [
    { path: 'was-waere-wenn', label: 'Was-wäre-wenn', Component: page(() => import('./pages/WhatifPage'), 'WhatifPage') },
    { path: 'splitter', label: 'Splitter', Component: page(() => import('./pages/SplitterPage'), 'SplitterPage') },
    { path: 'sensitivitaet', label: 'Sensitivität', Component: page(() => import('./pages/SensitivityPage'), 'SensitivityPage') },
    { path: 'risiko', label: 'Risiko', Component: page(() => import('./pages/RiskPage'), 'RiskPage') },
    { path: 'pareto', label: 'Erlös ↔ CO₂', Component: page(() => import('./pages/ParetoPage'), 'ParetoPage') },
  ] },
  { id: 'erloese', title: 'Erlöse & Technologie', icon: ICON.erloese, routes: [
    { path: 'erloes-stapel', label: 'Erlös-Stapel', Component: page(() => import('./pages/RevenueStackPage'), 'RevenueStackPage') },
    { path: 'plasma', label: 'Plasma vs. Elektrolyse', Component: page(() => import('./pages/PlasmaPage'), 'PlasmaPage') },
    { path: 'cdr', label: 'CDR-Preis', Component: page(() => import('./pages/CdrPage'), 'CdrPage') },
    { path: 'eeg', label: 'EEG-Jahresbudget', Component: page(() => import('./pages/EegPage'), 'EegPage') },
  ] },
  { id: 'prognose', title: 'Prognose & Markt', icon: ICON.prognose, routes: [
    { path: 'prognose', label: 'Prognose-Güte', Component: page(() => import('./pages/ForecastPage'), 'ForecastPage') },
    { path: 'prognoseband', label: 'Prognoseband', Component: page(() => import('./pages/ForecastBandPage'), 'ForecastBandPage') },
    { path: 'markt', label: 'Markt', Component: page(() => import('./pages/MarketPage'), 'MarketPage') },
    { path: 'datenanalyse', label: 'Datenanalyse', Component: page(() => import('./pages/DataAnalysisPage'), 'DataAnalysisPage') },
  ] },
  { id: 'nachweis', title: 'Nachweis', icon: ICON.nachweis, routes: [
    { path: 'backtest', label: 'Backtest', Component: page(() => import('./pages/BacktestPage'), 'BacktestPage') },
    { path: 'schattenbetrieb', label: 'Schattenbetrieb', Component: page(() => import('./pages/ShadowPage'), 'ShadowPage') },
    { path: 'speicher', label: 'Speicher & MPC', Component: page(() => import('./pages/MpcPage'), 'MpcPage') },
  ] },
  { id: 'anlage', title: 'Anlage', icon: ICON.anlage, routes: [
    { path: 'anlagendaten', label: 'Anlagendaten', Component: page(() => import('./pages/PlantConfigPage'), 'PlantConfigPage') },
  ] },
]
const ROUTES = NAV.flatMap((g) => g.routes)

type Theme = 'light' | 'dark'
type Tab = 'module' | 'enno'

function readHash(): string {
  return window.location.hash.replace(/^#\/?/, '') || 'cockpit'
}

function initialTheme(): Theme {
  try {
    const t = localStorage.getItem('fldos_theme')
    if (t === 'light' || t === 'dark') return t
  } catch { /* Storage gesperrt → Systemeinstellung */ }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

// Theme vor dem Montieren der Charts setzen (Kind-Effects laufen vor Eltern-Effects).
function applyTheme(t: Theme): void {
  document.documentElement.dataset.theme = t
  applyChartTheme()
  try { localStorage.setItem('fldos_theme', t) } catch { /* nur Komfort */ }
}
const THEME0 = initialTheme()
applyTheme(THEME0)

function Icon({ d, size = 18 }: { d: string; size?: number }) {
  return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
}

function StatusPill() {
  const [st, setSt] = useState<StatusData | null>(null)
  const [down, setDown] = useState(false)
  useEffect(() => {
    const load = () => fldApi.status().then((s) => { setSt(s); setDown(false) }).catch(() => setDown(true))
    load()
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [])
  const color = down ? 'var(--c-neg)' : st?.stale ? 'var(--brand)' : 'var(--c-pos)'
  const day = st?.latest_target_day ? st.latest_target_day.split('-').reverse().join('.') : '—'
  const text = down ? 'Backend offline' : !st ? 'prüft …' : st.stale ? `Daten vom ${day}` : `Fahrplan ${day}`
  return <span className="pill" title={st?.stale ? 'Der jüngste Fahrplan liegt in der Vergangenheit — Tageskette neu laufen lassen.' : 'Datenbank und Datenfrische'}><span className="dot" style={{ background: color }} />{text}</span>
}

export function App() {
  const [path, setPath] = useState(readHash)
  const [theme, setTheme] = useState<Theme>(THEME0)
  const [menu, setMenu] = useState(false)
  const [tab, setTab] = useState<Tab>(() => (readHash() === 'assistent' ? 'enno' : 'module'))
  const [enno, setEnno] = useState<EnnoState>({ messages: [], sessionId: null })
  const [pending, setPending] = useState<string | null>(null)

  const route = ROUTES.find((r) => r.path === path) ?? ROUTES[0]
  const group = NAV.find((g) => g.routes.includes(route)) ?? NAV[0]
  const [open, setOpen] = useState<Set<string>>(() => new Set([group.id]))

  useEffect(() => {
    const on = () => {
      const p = readHash()
      if (p === 'assistent') { setTab('enno'); setMenu(true); return }
      setPath(p)
      setMenu(false)
      const g = NAV.find((x) => x.routes.some((r) => r.path === p))
      if (g) setOpen((o) => new Set(o).add(g.id))
    }
    const ask = (e: Event) => { setTab('enno'); setMenu(true); setPending((e as CustomEvent<string>).detail) }
    window.addEventListener('hashchange', on)
    window.addEventListener('enno:ask', ask)
    return () => { window.removeEventListener('hashchange', on); window.removeEventListener('enno:ask', ask) }
  }, [])

  const toggle = (id: string) => setOpen((o) => { const n = new Set(o); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const Page = route.Component

  return (
    <div className="shell">
      <nav className={`sidebar${menu ? ' open' : ''}${tab === 'enno' ? ' wide' : ''}`} aria-label="Navigation">
        <div className="side-top">
          <a href="#/cockpit" className="side-logo"><Logo /></a>
          <div className="tenant">{BRAND.tenant}<span>1 MWel · Modell</span></div>
          <div className="side-tabs" role="tablist">
            <button role="tab" aria-selected={tab === 'module'} onClick={() => setTab('module')}>Module</button>
            <button role="tab" aria-selected={tab === 'enno'} onClick={() => setTab('enno')}>
              <EnnoAvatar size={18} /> Enno
            </button>
          </div>
        </div>

        {tab === 'module' ? (
          <div className="side-nav">
            {NAV.map((g) => {
              const isOpen = open.has(g.id)
              const active = g.id === group.id
              return (
                <div key={g.id} className={`nav-group${active ? ' active' : ''}`}>
                  <button className="nav-head" aria-expanded={isOpen} onClick={() => toggle(g.id)}>
                    <Icon d={g.icon} /><span>{g.title}</span><span className="chev" aria-hidden="true">{isOpen ? '−' : '+'}</span>
                  </button>
                  {isOpen && g.routes.map((r) => (
                    <a key={r.path} className="nav" href={`#/${r.path}`} aria-current={r.path === route.path ? 'page' : undefined}>{r.label}</a>
                  ))}
                </div>
              )
            })}
            <button className="enno-teaser" onClick={() => setTab('enno')}>
              <EnnoAvatar size={30} />
              <span><strong>Frag Enno</strong><br />„Was soll die Anlage morgen tun?“</span>
            </button>
          </div>
        ) : (
          <EnnoPanel state={enno} setState={setEnno} page={route.path} pending={pending} onPendingDone={() => setPending(null)} />
        )}
      </nav>

      <div className="main">
        <header className="topbar">
          <button className="btn menu-btn" onClick={() => setMenu(!menu)} aria-label="Navigation öffnen">☰</button>
          <div className="crumb">
            <span className="crumb-group"><Icon d={group.icon} size={16} /> {group.title} <span style={{ color: 'var(--fld-faint)' }}>/</span></span> <strong>{route.label}</strong>
          </div>
          <div style={{ flex: 1 }} />
          <StatusPill />
          <button className="btn icon-btn" onClick={() => { const t = theme === 'dark' ? 'light' : 'dark'; applyTheme(t); setTheme(t) }} aria-label="Hell/Dunkel umschalten">{theme === 'dark' ? '☀' : '☾'}</button>
        </header>
        <main className="content" tabIndex={0}>
          <Suspense fallback={<div className="page"><Skeleton height={400} /></div>}>
            <Page key={`${route.path}-${theme}`} />
          </Suspense>
        </main>
      </div>
    </div>
  )
}
