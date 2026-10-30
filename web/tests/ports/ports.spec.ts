// F1: Jeder Lauf bekommt eigene freie Ports; Konfiguration und Variablen folgen ihnen.
import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { WEB, cleanEnv, freePort, listenOn, portOf, readJson, start } from './helpers'

const PROBE = path.join('tests', 'ports', 'probe', 'probe.config.ts')

async function probe(tmp: string, name: string, env: Record<string, string | undefined> = {}, peer?: string) {
  const out = path.join(tmp, `${name}.json`)
  const child = start('npx', ['playwright', 'test', '-c', PROBE], cleanEnv({ PROBE_OUT: out, PROBE_PEER: peer, PROBE_TMP: path.join(tmp, `pw-${name}`), ...env }))
  return { out, child }
}

interface Report { baseURL: string; outputDir: string | null; webServer: { url: string; command: string; env: Record<string, string> }[]; workerEnv: { backend: string | null; vite: string | null } }
const backendOf = (r: Report) => r.webServer.find((w) => new URL(w.url).pathname.endsWith('/api/v1/health'))!
const viteOf = (r: Report) => r.webServer.find((w) => !new URL(w.url).pathname.endsWith('/api/v1/health'))!

test('e2e/ports.ts: allocatePorts() liefert zwei verschiedene freie Ports, auch während andere belegt sind', async () => {
  const file = path.join(WEB, 'e2e', 'ports.ts')
  expect(fs.existsSync(file), 'web/e2e/ports.ts fehlt (soll allocatePorts(): Promise<{backend:number; vite:number}> exportieren)').toBe(true)
  const { allocatePorts } = await import(file)
  const a = await allocatePorts()
  expect(Number.isInteger(a.backend) && Number.isInteger(a.vite)).toBe(true)
  expect(a.backend).not.toBe(a.vite)
  const held = [await listenOn(a.backend), await listenOn(a.vite)] // beide wirklich frei gewesen
  try {
    const b = await allocatePorts()
    expect([b.backend, b.vite].filter((p) => [a.backend, a.vite].includes(p))).toEqual([])
  } finally {
    held.forEach((s) => s.close())
  }
})

test('zwei gleichzeitige Läufe: eigene, kollisionsfreie Ports (belegt wie echte Server)', async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'fld-ports-'))
  const a = await probe(tmp, 'a', {}, path.join(tmp, 'b.json'))
  const b = await probe(tmp, 'b', {}, path.join(tmp, 'a.json'))
  const [ca, cb] = await Promise.all([a.child.exited, b.child.exited])
  expect(ca, `Lauf A:\n${a.child.out()}`).toBe(0)
  expect(cb, `Lauf B:\n${b.child.out()}`).toBe(0)
  const ra: Report = readJson(a.out)
  const rb: Report = readJson(b.out)
  const ports = (r: Report) => r.webServer.map((w) => portOf(w.url))
  expect(ports(ra)).toHaveLength(2)
  expect(ports(ra).filter((p) => ports(rb).includes(p)), 'gemeinsame Ports beider Läufe').toEqual([])
  expect(new Set(ports(ra)).size).toBe(2)
})

test('Konfiguration ist in sich stimmig: baseURL, Health-URL, Backend-Port, Vite-Port und Proxy-Ziel', async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'fld-ports-'))
  const p = await probe(tmp, 'x', { FLD_E2E_BACKEND_PORT: String(await freePort()), FLD_E2E_VITE_PORT: String(await freePort()) })
  expect(await p.child.exited, p.child.out()).toBe(0)
  const r: Report = readJson(p.out)
  const be = portOf(backendOf(r).url)
  const vi = portOf(viteOf(r).url)
  expect(portOf(r.baseURL)).toBe(vi)
  expect(backendOf(r).env.FLD_PORT, 'Backend-Server bekommt seinen Port über FLD_PORT').toBe(String(be))
  expect(viteOf(r).env.FLD_WEB_PORT, 'Vite bekommt seinen Port über FLD_WEB_PORT').toBe(String(vi))
  expect(viteOf(r).env.FLD_API_URL, 'Vite-Proxy zeigt auf das Backend dieses Laufs').toBe(`http://127.0.0.1:${be}`)
  expect(backendOf(r).url).toBe(`http://127.0.0.1:${be}/api/v1/health`)
})

test('FLD_E2E_BACKEND_PORT / FLD_E2E_VITE_PORT legen die Ports fest (einzelner Lauf wie bisher möglich)', async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'fld-ports-'))
  const be = await freePort()
  const vi = await freePort()
  const p = await probe(tmp, 'pinned', { FLD_E2E_BACKEND_PORT: String(be), FLD_E2E_VITE_PORT: String(vi) })
  expect(await p.child.exited, p.child.out()).toBe(0)
  const r: Report = readJson(p.out)
  expect(portOf(backendOf(r).url)).toBe(be)
  expect(portOf(viteOf(r).url)).toBe(vi)
  expect(portOf(r.baseURL)).toBe(vi)
  // Der Worker-Prozess sieht dieselben Ports (die Konfiguration gibt sie per Umgebung weiter, global-setup und Tests lesen sie dort).
  expect(r.workerEnv).toEqual({ backend: String(be), vite: String(vi) })
})
