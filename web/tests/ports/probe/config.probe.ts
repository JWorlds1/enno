import { test } from '@playwright/test'
import fs from 'node:fs'
import net from 'node:net'
import real from '../../../playwright.config'

const asList = (w: unknown) => (Array.isArray(w) ? w : w ? [w] : []) as { url?: string; command?: string; env?: Record<string, string>; reuseExistingServer?: boolean }[]

test('Konfiguration melden, Ports belegen, auf den Nachbarlauf warten', async () => {
  const servers = asList(real.webServer)
  const report = {
    baseURL: real.use?.baseURL ?? null,
    outputDir: real.outputDir ?? null,
    webServer: servers.map((w) => ({ url: w.url ?? null, command: w.command ?? null, env: w.env ?? {} })),
    workerEnv: { backend: process.env.FLD_E2E_BACKEND_PORT ?? null, vite: process.env.FLD_E2E_VITE_PORT ?? null },
  }
  fs.writeFileSync(process.env.PROBE_OUT!, JSON.stringify(report))
  // Wie ein laufender Lauf: die Ports aus den webServer-URLs wirklich belegen. Kollidiert ein Nachbarlauf, schlägt listen fehl.
  const held: net.Server[] = []
  for (const w of servers) {
    if (!w.url) continue
    const port = Number(new URL(w.url).port)
    await new Promise<void>((resolve, reject) => {
      const s = net.createServer()
      s.once('error', reject)
      s.listen(port, '127.0.0.1', () => { held.push(s); resolve() })
    })
  }
  const peer = process.env.PROBE_PEER
  if (peer) {
    const t0 = Date.now()
    while (!fs.existsSync(peer)) {
      if (Date.now() - t0 > 40_000) throw new Error('Nachbarlauf hat sich nicht gemeldet')
      await new Promise((r) => setTimeout(r, 100))
    }
    await new Promise((r) => setTimeout(r, 500)) // Nachbar soll seine Ports inzwischen auch belegt haben
  }
  held.forEach((s) => s.close())
})
