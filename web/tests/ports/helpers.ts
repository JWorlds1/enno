import { spawn, type ChildProcess } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Freien Port von der Umgebung geben lassen (kurz binden, wieder freigeben). */
export function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const s = net.createServer()
    s.once('error', reject)
    s.listen(0, '127.0.0.1', () => {
      const { port } = s.address() as net.AddressInfo
      s.close(() => resolve(port))
    })
  })
}

/** Port belegen wie ein laufender Server; Fehler (EADDRINUSE) werden durchgereicht. */
export function listenOn(port: number, host = '127.0.0.1'): Promise<net.Server> {
  return new Promise((resolve, reject) => {
    const s = net.createServer()
    s.once('error', reject)
    s.listen(port, host, () => resolve(s))
  })
}

/** Umgebung für Kindprozesse: ohne die Variablen des umgebenden Playwright-Laufs und ohne alte Port-Vorgaben. */
export function cleanEnv(extra: Record<string, string | undefined> = {}): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {}
  for (const [k, v] of Object.entries(process.env)) {
    if (/^(PW_|PLAYWRIGHT_|TEST_WORKER_INDEX|TEST_PARALLEL_INDEX|FLD_E2E_|FLD_WEB_PORT|FLD_PORT|FLD_API_URL)/.test(k)) continue
    env[k] = v
  }
  for (const [k, v] of Object.entries(extra)) { if (v === undefined) delete env[k]; else env[k] = v }
  return env
}

export interface Child { proc: ChildProcess; out: () => string; exited: Promise<number | null>; stop: () => Promise<void> }

export function start(cmd: string, args: string[], env: NodeJS.ProcessEnv, cwd = WEB): Child {
  const proc = spawn(cmd, args, { cwd, env, detached: true, stdio: ['ignore', 'pipe', 'pipe'] })
  let buf = ''
  proc.stdout!.on('data', (d) => { buf += d })
  proc.stderr!.on('data', (d) => { buf += d })
  const exited = new Promise<number | null>((res) => proc.on('exit', (code) => res(code)))
  const stop = async () => {
    if (proc.exitCode === null && proc.pid) { try { process.kill(-proc.pid, 'SIGTERM') } catch { /* schon beendet */ } }
    await Promise.race([exited, sleep(5000)])
    if (proc.exitCode === null && proc.pid) { try { process.kill(-proc.pid, 'SIGKILL') } catch { /* schon beendet */ } }
  }
  return { proc, out: () => buf, exited, stop }
}

export async function until<T>(what: string, fn: () => Promise<T | undefined | false> | T | undefined | false, ms = 30_000): Promise<T> {
  const t0 = Date.now()
  for (;;) {
    try { const v = await fn(); if (v) return v as T } catch { /* noch nicht */ }
    if (Date.now() - t0 > ms) throw new Error(`Zeitüberschreitung (${ms} ms): ${what}`)
    await sleep(200)
  }
}

export const readJson = (f: string) => JSON.parse(fs.readFileSync(f, 'utf8'))
export const portOf = (url: string) => Number(new URL(url).port)
