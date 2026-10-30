// Wortmarke FLD OS: Ring-Motiv (Gelb/Grau, angelehnt an den FLD-Auftritt) + Schriftzug. Eigene Zeichnung, kein FLD-Logo-Asset.
export function Logo({ size = 30 }: { size?: number }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
      <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
        <path d="M16 3a13 13 0 0 1 12.6 9.8" fill="none" style={{ stroke: 'var(--brand)' }} strokeWidth="3" strokeLinecap="round" />
        <path d="M6.2 7.6A13 13 0 0 1 11 4" fill="none" style={{ stroke: 'var(--brand)' }} strokeWidth="3" strokeLinecap="round" />
        <path d="M28.8 18.5A13 13 0 0 1 4.6 22.4" fill="none" stroke="#a39e9e" strokeWidth="3" strokeLinecap="round" />
        <circle cx="16" cy="16" r="4.2" style={{ fill: 'var(--brand)' }} />
      </svg>
      <span className="brand-font" style={{ fontWeight: 800, fontSize: 19, letterSpacing: '0.02em' }}>
        FLD <span style={{ color: 'var(--brand)' }}>OS</span>
      </span>
    </span>
  )
}
