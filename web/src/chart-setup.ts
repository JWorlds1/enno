// chart.js zentral konfigurieren: Controller registrieren, Schrift/Raster aus den Theme-Tokens,
// und ein Plugin, das 'var(--token)' in Dataset-Farben zur Laufzeit auflöst (Canvas kennt keine CSS-Variablen).
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, BarElement,
  Tooltip, Legend, Filler, ScatterController, LineController, BarController, type Plugin,
} from 'chart.js'

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement, BarElement,
  Tooltip, Legend, Filler, ScatterController, LineController, BarController,
)

const COLOR_KEYS = ['borderColor', 'backgroundColor', 'pointBackgroundColor', 'pointBorderColor'] as const

export function cssVar(value: string): string {
  const m = /^var\((--[\w-]+)\)$/.exec(value.trim())
  if (!m) return value
  return getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() || value
}

const resolveVars: Plugin = {
  id: 'resolveCssVars',
  beforeUpdate(chart) {
    for (const ds of chart.data.datasets as unknown as Record<string, unknown>[]) {
      const src = (ds._src ??= {}) as Record<string, unknown>
      for (const k of COLOR_KEYS) {
        if (typeof ds[k] === 'string' && (ds[k] as string).startsWith('var(')) src[k] = ds[k]
        if (typeof src[k] === 'string') ds[k] = cssVar(src[k] as string)
      }
    }
  },
}
ChartJS.register(resolveVars)

// Screenreader: jedes Diagramm ist ein beschriftetes Bild („Diagramm: BHKW MW, Strompreis …“).
const a11y: Plugin = {
  id: 'canvasA11y',
  afterUpdate(chart) {
    const names = chart.data.datasets.map((d) => d.label).filter((l): l is string => !!l && !l.endsWith('unten'))
    chart.canvas.setAttribute('role', 'img')
    chart.canvas.setAttribute('aria-label', `Diagramm: ${names.join(', ') || 'Daten'}`)
  },
}
ChartJS.register(a11y)

/** Nach Theme-Wechsel aufrufen, danach Charts neu montieren. */
export function applyChartTheme(): void {
  ChartJS.defaults.font.family = "'Open Sans', system-ui, sans-serif"
  ChartJS.defaults.font.size = 12
  ChartJS.defaults.color = cssVar('var(--fld-muted)')
  ChartJS.defaults.borderColor = cssVar('var(--c-grid)')
  ChartJS.defaults.plugins.legend.labels.usePointStyle = true
  ChartJS.defaults.plugins.tooltip.backgroundColor = cssVar('var(--tooltip-bg)')
  ChartJS.defaults.plugins.tooltip.titleColor = cssVar('var(--tooltip-ink)')
  ChartJS.defaults.plugins.tooltip.bodyColor = cssVar('var(--tooltip-ink)')
}
