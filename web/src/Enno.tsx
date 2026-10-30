// Enno in der linken Leiste: Chat mit echten Zahlen, Vorschläge je Seite, Sprunglinks zu den Modulen.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { fldApi, type ChatTurn } from './lib/api'

export interface EnnoMessage extends ChatTurn {
  actions?: { label: string; route: string }[]
}

export interface EnnoState {
  messages: EnnoMessage[]
  sessionId: number | null
}

const GENERAL = ['Was soll die Anlage morgen tun?', 'Warum diese Strategie?', 'Rechne mit Gaspreis 100', 'Lohnt sich Plasma?']
const BY_PAGE: Record<string, string[]> = {
  cockpit: ['Was soll die Anlage morgen tun?', 'Warum diese Strategie?', 'Wie gut war der Backtest?'],
  'was-waere-wenn': ['Rechne mit Gaspreis 100 und H₂-Wert 150', 'Rechne mit CO₂ 150 und Elektrolyse'],
  sensitivitaet: ['Was sehe ich hier?', 'Rechne mit Gaspreis 50'],
  risiko: ['Was sehe ich hier?', 'Was bringt die Absicherung?'],
  pareto: ['Was sehe ich hier?', 'Lohnt sich CO₂-Vermeidung?'],
  'erloes-stapel': ['Was bringt Regelenergie?', 'Was sehe ich hier?'],
  plasma: ['Lohnt sich Plasma?', 'Rechne mit CO₂ 200'],
  cdr: ['Lohnt sich Plasma?', 'Rechne mit CO₂ 200'],
  prognoseband: ['Wie unsicher ist die Prognose?', 'Was sehe ich hier?'],
  backtest: ['Wie gut war der Backtest?'],
  speicher: ['Was bringt der Speicher?', 'Was sehe ich hier?'],
  markt: ['Wie steht der Markt?'],
}

/** Minimal-Markdown: **fett**, Aufzählungen mit „- “, Absätze. Kein HTML aus der Antwort. */
function Rich({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/)
  const inline = (s: string): ReactNode[] =>
    s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>)
  return (
    <>
      {blocks.map((b, i) => {
        const lines = b.split('\n')
        const bullets = lines.filter((l) => l.startsWith('- '))
        const head = lines.filter((l) => !l.startsWith('- '))
        return (
          <div key={i} style={{ marginTop: i ? 8 : 0 }}>
            {head.map((l, j) => <div key={j}>{inline(l)}</div>)}
            {bullets.length > 0 && <ul>{bullets.map((l, j) => <li key={j}>{inline(l.slice(2))}</li>)}</ul>}
          </div>
        )
      })}
    </>
  )
}

export function EnnoAvatar({ size = 34, busy = false }: { size?: number; busy?: boolean }) {
  return (
    <span className={`enno-avatar${busy ? ' busy' : ''}`} style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 32 32" width={size * 0.62} height={size * 0.62}>
        <path d="M16 4a12 12 0 0 1 11.6 9" fill="none" style={{ stroke: 'var(--brand)' }} strokeWidth="3.2" strokeLinecap="round" />
        <path d="M27.6 18.8A12 12 0 0 1 5.3 21.6" fill="none" stroke="#d8d4d0" strokeWidth="3.2" strokeLinecap="round" />
        <circle cx="16" cy="16" r="4.4" style={{ fill: 'var(--brand)' }} />
      </svg>
    </span>
  )
}

export function EnnoPanel({ state, setState, page, pending, onPendingDone }: {
  state: EnnoState
  setState: (s: EnnoState) => void
  page: string
  pending: string | null
  onPendingDone: () => void
}) {
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState<'basis' | 'llm'>('basis')
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [state.messages, busy])
  useEffect(() => { inputRef.current?.focus() }, [])

  async function send(text: string) {
    const q = text.trim()
    if (!q || busy) return
    const history: ChatTurn[] = state.messages.map(({ role, content }) => ({ role, content }))
    const next: EnnoMessage[] = [...state.messages, { role: 'user', content: q }]
    setState({ ...state, messages: next })
    setInput('')
    setBusy(true)
    try {
      const r = await fldApi.chat({ message: q, history, session_id: state.sessionId, page })
      setMode(r.mode)
      setState({ sessionId: r.session_id, messages: [...next, { role: 'assistant', content: r.reply, actions: r.actions }] })
    } catch (e) {
      setState({ ...state, messages: [...next, { role: 'assistant', content: `Ich komme gerade nicht an die Daten (${e instanceof Error ? e.message : String(e)}).` }] })
    } finally {
      setBusy(false)
    }
  }

  // Fragen, die andere Seiten an Enno schicken (z. B. „Warum?“ im Cockpit)
  useEffect(() => {
    if (pending) { void send(pending); onPendingDone() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending])

  const suggestions = BY_PAGE[page] ?? GENERAL
  const empty = state.messages.length === 0

  return (
    <div className="enno">
      <div className="enno-head">
        <EnnoAvatar busy={busy} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>Enno</div>
          <div className="enno-sub"><span className="dot" style={{ background: busy ? 'var(--brand)' : 'var(--c-pos)' }} />
            {busy ? 'rechnet …' : mode === 'llm' ? 'Sprachmodell · echte Daten' : 'bereit · rechnet mit echten Daten'}</div>
        </div>
        {!empty && <button className="enno-reset" onClick={() => setState({ messages: [], sessionId: null })} title="Neues Gespräch">Neu</button>}
      </div>

      <div className="enno-log" aria-live="polite">
        {empty && (
          <div className="enno-hello">
            <div style={{ fontFamily: 'Montserrat, sans-serif', fontWeight: 700, fontSize: 18, marginBottom: 6 }}>Hallo, ich bin Enno.</div>
            Ich kenne die Zahlen dieser Anlage und rechne für dich nach. Frag einfach.
          </div>
        )}
        {state.messages.map((m, i) => (
          <div key={i} className={`enno-msg ${m.role}`}>
            <div className="bubble">{m.role === 'assistant' ? <Rich text={m.content} /> : m.content}</div>
            {m.actions && m.actions.length > 0 && (
              <div className="enno-actions">
                {m.actions.map((a) => <a key={a.route + a.label} href={`#/${a.route}`}>{a.label} →</a>)}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="enno-msg assistant"><div className="bubble typing"><span /><span /><span /></div></div>}
        <div ref={endRef} />
      </div>

      <div className="enno-suggest">
        {suggestions.map((s) => <button key={s} onClick={() => send(s)} disabled={busy}>{s}</button>)}
      </div>

      <form className="enno-input" onSubmit={(e) => { e.preventDefault(); void send(input) }}>
        <textarea ref={inputRef} rows={1} value={input} placeholder="Frag Enno …" onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(input) } }} />
        <button type="submit" disabled={busy || !input.trim()} aria-label="Senden">
          <svg viewBox="0 0 24 24" width="18" height="18"><path d="M4 12h14M12 5l7 7-7 7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
      </form>
    </div>
  )
}

/** Von jeder Seite aus Enno eine Frage stellen: öffnet den Enno-Reiter und schickt die Frage ab. */
export function askEnno(question: string): void {
  window.dispatchEvent(new CustomEvent('enno:ask', { detail: question }))
}
