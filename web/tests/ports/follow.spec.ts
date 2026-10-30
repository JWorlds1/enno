// F2/F3: Backend-Skript, Vite (Port + Proxy) und Vorwärmen folgen den Ports, die der Lauf ihnen vorgibt.
import { test, expect } from '@playwright/test'
import http from 'node:http'
import path from 'node:path'
import { WEB, cleanEnv, freePort, listenOn, sleep, start, until } from './helpers'

function fakeBackend(port: number) {
  const seen: string[] = []
  const server = http.createServer((req, res) => {
    seen.push(req.url ?? '')
    res.setHeader('content-type', 'application/json')
    res.end('{"status":"ok"}')
  })
  return new Promise<{ seen: string[]; close: () => void }>((resolve) =>
    server.listen(port, '127.0.0.1', () => resolve({ seen, close: () => server.close() })))
}

test('run-backend.sh startet uvicorn auf FLD_PORT (ohne Postgres, memory://)', async () => {
  const port = await freePort()
  const child = start('bash', [path.join(WEB, '..', 'run-backend.sh')], cleanEnv({ FLD_PORT: String(port), FLD_DATABASE_URL: 'memory://', FLD_WARMUP: '0' }), path.join(WEB, '..'))
  try {
    const body = await until(`Health auf Port ${port}\n${child.out()}`, async () => {
      const r = await fetch(`http://127.0.0.1:${port}/api/v1/health`)
      return r.ok ? r.text() : undefined
    }, 40_000).catch((e) => { throw new Error(`${e.message}\nAusgabe des Skripts:\n${child.out()}`) })
    expect(body).toContain('ok')
  } finally {
    await child.stop()
  }
})

test('Vite hört auf FLD_WEB_PORT und proxyt /fld-api/<pfad> an FLD_API_URL als /api/v1/<pfad>', async () => {
  const be = await freePort()
  const vi = await freePort()
  const fake = await fakeBackend(be)
  const child = start('npx', ['vite'], cleanEnv({ FLD_WEB_PORT: String(vi), FLD_API_URL: `http://127.0.0.1:${be}` }))
  try {
    const r = await until(`Vite auf Port ${vi}\n${child.out()}`, async () => {
      const x = await fetch(`http://localhost:${vi}/fld-api/health`)
      return x.ok ? x : undefined
    }, 40_000).catch((e) => { throw new Error(`${e.message}\nAusgabe von Vite:\n${child.out()}`) })
    expect(await r.text()).toContain('ok')
    expect(fake.seen).toContain('/api/v1/health')
  } finally {
    await child.stop()
    fake.close()
  }
})

test('Vite weicht nicht still auf einen anderen Port aus, wenn FLD_WEB_PORT belegt ist (strictPort)', async () => {
  const vi = await freePort()
  const blocker = await listenOn(vi, '127.0.0.1')
  const blockerV6 = await listenOn(vi, '::1').catch(() => null)
  const child = start('npx', ['vite'], cleanEnv({ FLD_WEB_PORT: String(vi) }))
  try {
    const code = await Promise.race([child.exited, sleep(25_000).then(() => 'läuft weiter' as const)])
    expect(code, `Vite hätte mit Fehler enden müssen:\n${child.out()}`).not.toBe('läuft weiter')
    expect(code).not.toBe(0)
  } finally {
    await child.stop()
    blocker.close()
    blockerV6?.close()
  }
})

test('global-setup wärmt über das Backend am Port aus FLD_E2E_BACKEND_PORT vor', async () => {
  const port = await freePort()
  const fake = await fakeBackend(port)
  const before = process.env.FLD_E2E_BACKEND_PORT
  process.env.FLD_E2E_BACKEND_PORT = String(port)
  try {
    const mod = await import(path.join(WEB, 'e2e', 'global-setup.ts'))
    await mod.default()
    const paths = fake.seen.map((u) => u.split('?')[0])
    expect(paths).toEqual(expect.arrayContaining(['/api/v1/risk', '/api/v1/pareto', '/api/v1/revenue-stack', '/api/v1/plasma-compare', '/api/v1/forecast-band', '/api/v1/mpc']))
  } finally {
    if (before === undefined) delete process.env.FLD_E2E_BACKEND_PORT; else process.env.FLD_E2E_BACKEND_PORT = before
    fake.close()
  }
})
