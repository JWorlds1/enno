// FLD-OS-API-Client — same-origin über /fld-api (Vite-Proxy bzw. Reverse-Proxy → /api/v1), JWT optional aus localStorage.
const FLD_API = '/fld-api'

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('fldos_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${FLD_API}${path}`, { credentials: 'include', headers: authHeaders() })
  if (!r.ok) throw new Error(`FLD ${path} -> ${r.status}`)
  return r.json() as Promise<T>
}

async function post<T>(path: string, body: unknown, method = 'POST'): Promise<T> {
  const r = await fetch(`${FLD_API}${path}`, {
    method,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${path} → ${r.status}${r.status === 422 ? ': ' + (await r.json()).detail : ''}`)
  return r.json() as Promise<T>
}

const put = <T,>(path: string, body: unknown) => post<T>(path, body, 'PUT')

// ── Contract-Typen (spiegeln die Pydantic-Response-Models des Backends) ──
export interface DispatchSlot {
  slot: number
  ts: string | null
  pred_price: number | null
  bhkw_mw: number | null
  electrolyser_mw: number | null
  pyro_mw: number | null
  reserve_up_mw?: number | null    // nur bei Strategie „Regelenergie vorhalten“
  reserve_down_mw?: number | null
}
export interface Recommendation {
  target_day: string
  algo: string
  kpis: Record<string, unknown> | null
  created_at: string | null
  slots: DispatchSlot[]
}
export interface ForecastPoint {
  ts: string
  actual: number | null
  pred_a: number | null
  pred_b: number | null
  p10: number | null
  p90: number | null
}
export interface BacktestPoint {
  day: string
  algo: string
  flat: number | null
  perfect: number | null
  forecast: number | null
  up_fc: number | null
  up_pf: number | null
  ok: boolean | null
}
export interface FundamentalPoint {
  day: string
  ttf_gas_eur_mwh: number | null
  eua_co2_eur_t: number | null
}
export interface RegelPoint {
  day: string
  product: string
  price_eur_mw_h: number
}
export interface DecisionOut {
  strategy: string
  label: string | null
  scores: Record<string, number> | null
  guardrails: Record<string, unknown> | null
  rationale: string[] | null
  summary?: string | null
}
export interface ValueOut {
  days: number
  from_day: string
  to_day: string
  uplift_eur: number
  per_day_eur: number
  per_year_eur: number
  pct_vs_flat: number | null
  capture_pct: number | null
}
export type PtxMode = 'none' | 'electro' | 'plasma'
export interface WhatifIn {
  gas: number
  h2: number
  co2: number
  mode: PtxMode
  algo?: string
}
export interface WhatifOut {
  net_eur: number
  flat_eur: number
  uplift_eur: number
  spot: number
  heat: number
  h2_eur: number
  carbon_eur: number
  h2_mwh: number
  carbon_t: number
  elcost: number
  gas_cost: number
  starts: number
  bhkw_h: number
  status: string
  bhkw: number[]
  electro: number[]
  pyro: number[]
  marktwert_eur_mwh?: number | null
  praemie_eur_mwh?: number | null
  praemie_mwh?: number | null
  eeg_premium_eur?: number | null
  flex_eur?: number | null
  net_eeg_eur?: number | null
}

// ── Fetchers ──
// Pfade OHNE /api/v1 — der nginx-Rewrite /fld-api/(.*) → /api/v1/$1 (bzw. der Vite-Proxy) ergänzt es.
export const fldApi = {
  health: () => get<{ status: string }>('/health'),
  recommendation: (algo?: string) =>
    get<Recommendation>(`/recommendation${algo ? `?algo=${algo}` : ''}`),
  decision: () => get<DecisionOut>('/decision'),
  forecast: () => get<ForecastPoint[]>('/forecast'),
  backtest: (algo?: string) => get<BacktestPoint[]>(`/backtest${algo ? `?algo=${algo}` : ''}`),
  market: () => get<FundamentalPoint[]>('/market'),
  value: () => get<ValueOut>('/value'),
  regelenergie: () => get<RegelPoint[]>('/regelenergie'),
  whatif: (body: WhatifIn) => post<WhatifOut>('/whatif', body),
  figures: () => get<FigureItem[]>('/figures'),
  chat: (body: { message: string; history: ChatTurn[]; session_id?: number | null; page?: string }) => post<ChatReply>('/chat', body),
  priceHeatmap: () => get<HeatmapData>('/price-heatmap'),
  cdrSensitivity: (gas = 70, h2 = 100) => get<CdrData>(`/cdr-sensitivity?gas=${gas}&h2=${h2}`),
  eegBudget: (annualHours = 876, dailyHours = 8) => get<EegBudgetData>(`/eeg-budget?annual_hours=${annualHours}&daily_hours=${dailyHours}`),
  status: () => get<StatusData>('/status'),
  risk: () => get<RiskData>('/risk'),
  pareto: () => get<ParetoData>('/pareto'),
  revenueStack: (days = 7) => get<RevenueStackData>(`/revenue-stack?days=${days}`),
  plasmaCompare: (days = 10) => get<PlasmaData>(`/plasma-compare?days=${days}`),
  forecastBand: (days = 7) => get<ForecastBandData>(`/forecast-band?days=${days}`),
  mpc: (days = 14) => get<MpcData>(`/mpc?days=${days}`),
  sensitivity: (p: { gas: number; h2: number; co2: number; mode: PtxMode }) =>
    get<SensitivityData>(`/sensitivity?gas=${p.gas}&h2=${p.h2}&co2=${p.co2}&mode=${p.mode}`),
  valuePrices: () => get<ValuePricesData>('/value-prices'),
  splitter: (p: { carbon: CarbonPath; h2?: number; c?: number }) =>
    get<SplitterData>(`/splitter?carbon=${p.carbon}${p.h2 != null ? `&h2=${p.h2}` : ''}${p.c != null ? `&c=${p.c}` : ''}`),
  splitterPlan: (p: { carbon: CarbonPath; h2?: number; c?: number }) =>
    get<SplitterPlanData>(`/splitter-plan?carbon=${p.carbon}${p.h2 != null ? `&h2=${p.h2}` : ''}${p.c != null ? `&c=${p.c}` : ''}`),
  valueCurve: () => get<ValueCurveData>('/value-curve'),
  splitterYear: (carbon: CarbonPath) => get<SplitterYearData>(`/splitter-year?carbon=${carbon}`),
  splitterProof: (carbon: CarbonPath) => get<SplitterProofData>(`/splitter-proof?carbon=${carbon}`),
  plantConfig: () => get<PlantConfigData>('/plant-config'),
  setPlantConfig: (params: Record<string, number>) => put<PlantConfigData>('/plant-config', { params }),
}

export interface StatusData { status: string; db: string; latest_target_day: string | null; stale: boolean; memories: number }
export interface RiskData {
  day: string; scenarios: number; alpha: number
  rp: number; eev: number; ws: number; vss: number; evpi: number
  frontier: { lam: number; expected: number; cvar: number; bhkw_h: number }[]
}
export interface ParetoData {
  day: string; gas_cost: number; eua: number
  front: { co2_t: number; profit: number }[]
  slope_eur_t: number | null; cheaper_than_eua: boolean
}
export interface RevenueStackRow { day: string; spot_only: number; coopt: number; energy: number; capacity: number; uplift: number; reserve_mw: number }
export interface RevenueStackData { afrr: number; fcr: number; rows: RevenueStackRow[]; avg_uplift: number; uplift_per_mw_year: number }
export type CarbonPath = 'co2' | 'cdr' | 'black'
export interface PriceRef { date: string; source: string; url: string; comparable: boolean; note: string | null; ref_eur_kg: number | null; formula_eur_kg: number | null; deviation_pct: number | null }
export interface PriceCheck { status: string; factor: number; refs: PriceRef[] }
export interface PriceItem { eur_kg: number | null; source: string; formula: string; inputs: Record<string, number | null>; check?: PriceCheck | null }
export interface ValuePricesData { as_of: string; h2: PriceItem; carbon: Record<CarbonPath, PriceItem> }
export interface SplitSlot { time: string; price: number; route: 'strom' | 'plasma'; sure: boolean }
export interface SplitterData {
  target_day: string; price_basis: 'Prognose' | 'Auktion'; carbon: CarbonPath
  h2_eur_kg: number; c_eur_kg: number; own_prices: boolean; threshold_eur_mwh: number
  ratio: { el_kwh: number; h2_kg: number; c_kg: number; plasma_kwh: number }
  strom_slots: number; switches: number; unsure_slots: number; margin_eur_mwh: number; min_run_slots: number; block_slots: number
  blocks: string[]; revenue: { splitter: number; nur_strom: number; nur_plasma: number }
  uplift_vs_best: number; slots: SplitSlot[]
}
export interface CurveMonth {
  month: string; ttf_eur_mwh: number | null; brent_usd_bbl: number | null; h2: number | null
  carbon: Record<CarbonPath, number | null>; threshold: Record<CarbonPath, number | null>; interpolated: string[]
}
export interface ValueCurveData { as_of: string; eua_eur_t: number | null; eurusd: number | null; months: CurveMonth[] }
export interface SplitterPlanData {
  target_day: string; price_basis: 'Prognose' | 'Auktion'; status: string; times: string[]
  bhkw_mw: number[]; plasma_gas_mw: number[]; storage_mwh: number[]
  revenue: { splitter: number; nur_strom: number }; uplift_eur: number
  plasma_gas_mwh: number; h2_kg: number; c_kg: number; starts: number; bhkw_h: number
}
export interface SplitterYearData {
  carbon: CarbonPath; days: number; skipped: number; from: string; to: string; margin_eur_mwh: number; min_run_h: number
  per_year: { splitter: number; nur_strom: number; nur_plasma: number; ideal: number }
  uplift_vs_best_pct: number; capture_pct: number; switches_per_year: number; switches_per_day: number
  bhkw_share_pct: number; bhkw_runs_per_year: number; avg_run_h: number; short_runs_per_year: number
  correct_pct: number; unsure_pct: number
  bids: { per_year: number; capture_pct: number; switches_per_year: number; correct_pct: number }
  hourly_bhkw_pct: number[]; monthly: { month: string; bhkw_pct: number; uplift_eur: number }[]
  milp: { days: number; uplift_eur_per_day: number; plasma_gas_mwh_per_day: number; starts_per_day: number }
}
export type ProofStatus = 'abgerechnet' | 'kein Plan ausgegeben' | 'zu spät ausgegeben' | 'Ist-Preise fehlen noch' | 'keine Marktdaten'
export interface ProofDay {
  day: string; status: ProofStatus; issued: string | null; basis: 'Prognose' | 'Auktion' | null
  h2_eur_kg: number | null; c_eur_kg: number | null; threshold_eur_mwh: number | null
  revenue: { plan: number; nur_strom: number; nur_plasma: number; ideal: number; gebote: number } | null
  plus_vs_best_eur: number | null; capture_pct: number | null; switches: number | null; strom_slots: number | null
  correct_pct: number | null
}
export interface SplitterProofData {
  carbon: CarbonPath; days: ProofDay[]
  summary: {
    settled_days: number; missing_days: number; pending_days: number; late_days: number; streak_days: number
    forecast_days: number; plus_vs_best_eur: number; capture_pct: number; last_settled: string | null
  }
}
export interface PlasmaRow { day: string; power: number; electro: number; pyro: number; gas_pyro_mwh: number; h2_mwh: number; carbon_t: number }
export interface PlasmaData {
  rows: PlasmaRow[]; avg: { power: number; electro: number; pyro: number }
  uplift_electro: number; uplift_pyro: number; carbon_credit_eur_t: number
}
export interface BandPoint { ts: string; actual: number; raw_lo: number; raw_hi: number; aci_lo: number; aci_hi: number; aci_cov_24h: number }
export interface ForecastBandData {
  target: number; calib_n: number; test_n: number; cqr_q: number
  coverage: { raw: number; cqr: number; aci: number }
  width: { raw: number; cqr: number; aci: number }
  series: BandPoint[]
}
export interface MpcData {
  horizon: number; s_max: number; days: string[]
  base_eur: number[]; mpc_eur: number[]; total_base: number; total_mpc: number
  uplift_per_mw_year: number; level_base: number[]; level_mpc: number[]
}
export interface SensitivityBar { param: string; label: string; base_value: number; low_value: number; high_value: number; low_net: number; high_net: number; swing: number }
export interface SensitivityData { mode: PtxMode; delta: number; base_net: number; bars: SensitivityBar[]; with_eeg: boolean }
export interface PlantConfigData {
  defaults: Record<string, number>; override: Record<string, number>
  diff: Record<string, { default: number; plant: number }>; applied_to_optimizer: boolean; fixed: string[]
}

export interface EegBudgetData {
  ranking: 'prognose' | 'nachtraeglich'
  annual_hours: number
  daily_hours: number
  affordable_days: number
  total_days: number
  value_at_budget: number
  value_all: number
  pct_of_max: number
  cum_hours: number[]
  cum_value: number[]
}

export interface CdrRow {
  co2: number
  plasma_net: number
  plasma_uplift: number
  plasma_carbon_t: number
  plasma_h2_mwh: number
  plasma_pyro: number
  electro_net: number
}
export interface CdrData {
  rows: CdrRow[]
  break_even_co2: number | null
  gas: number
  h2: number
}

export interface HeatmapData {
  weekdays: string[]
  hours: number[]
  matrix: (number | null)[][]
  min: number
  max: number
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}
export interface ChatReply {
  reply: string
  tool_calls: { name: string; input: unknown }[]
  actions: { label: string; route: string }[]
  mode: 'basis' | 'llm'
  session_id: number
}

export interface FigureItem {
  name: string
  title: string
}
// Direkt-URL für <img>: geht über den nginx-/Vite-Rewrite auf /api/v1/figures/<name>
export const figureUrl = (name: string): string => `/fld-api/figures/${encodeURIComponent(name)}`

/** Biomethan heute = letzter TTF (Markt) + Biomethan-Aufschlag der Anlage — Startwert aller Gaspreis-Regler. */
export async function marketGas(): Promise<{ gas: number; ttf: number; premium: number } | null> {
  const [mk, cfg] = await Promise.all([fldApi.market(), fldApi.plantConfig()])
  const ttf = [...mk].sort((a, b) => b.day.localeCompare(a.day)).find((x) => x.ttf_gas_eur_mwh != null)?.ttf_gas_eur_mwh
  if (ttf == null) return null
  const premium = (cfg.override.bio_premium_eur_mwh ?? cfg.defaults.bio_premium_eur_mwh) as number
  return { gas: Math.round(ttf + premium), ttf, premium }
}

export interface ShadowDay {
  day: string; energy_rec_mwh: number; energy_meas_mwh: number; revenue_rec_eur: number; revenue_meas_eur: number
  price_rec_eur_mwh: number; price_meas_eur_mwh: number; extra_same_energy_eur: number
}
export interface ShadowData { days: ShadowDay[]; summary: { days: number; extra_same_energy_eur: number; per_day_eur: number | null }; measurements: number }
export const shadowApi = {
  get: () => get<ShadowData>('/shadow'),
  upload: (csv: string) => post<{ rows: number; from_ts: string | null; to_ts: string | null }>('/measurements', { csv }),
}

export interface ModelQuality { days: number; from_day: string; to_day: string; mae_eur_mwh: number; mae_naive_eur_mwh: number; bias_eur_mwh: number; coverage_p10_p90: number }
export const modelApi = { get: () => get<ModelQuality>('/model') }
