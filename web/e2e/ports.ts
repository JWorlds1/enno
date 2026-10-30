import { execFileSync } from 'node:child_process'
import net from 'node:net'

function listen(): Promise<net.Server> {
  return new Promise((resolve, reject) => {
    const s = net.createServer()
    s.once('error', reject)
    s.listen(0, '127.0.0.1', () => resolve(s))
  })
}

const portOf = (s: net.Server) => (s.address() as net.AddressInfo).port

// Zwei verschiedene, jetzt freie Ports auf 127.0.0.1. Beide werden gleichzeitig gehalten,
// damit sie sich unterscheiden, und erst danach freigegeben.
export async function allocatePorts(): Promise<{ backend: number; vite: number }> {
  const a = await listen()
  const b = await listen()
  const ports = { backend: portOf(a), vite: portOf(b) }
  await Promise.all([a, b].map((s) => new Promise<void>((r) => s.close(() => r()))))
  return ports
}

// Wie allocatePorts, aber synchron (die Konfiguration darf kein Top-Level-await enthalten, damit sie
// auch als CommonJS geladen werden kann): ein Kindprozess hält beide Listener, meldet die Ports und endet.
const SCRIPT = `
const net = require('node:net')
const l = () => new Promise((r) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => r(s)) })
;(async () => { const a = await l(), b = await l(); process.stdout.write(a.address().port + " " + b.address().port); process.exit(0) })()
`
export function allocatePortsSync(): { backend: number; vite: number } {
  const out = execFileSync(process.execPath, ['-e', SCRIPT], { encoding: 'utf8' }).trim().split(' ').map(Number)
  return { backend: out[0], vite: out[1] }
}
