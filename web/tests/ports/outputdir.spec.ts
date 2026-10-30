// F4: test-results/ eines Laufs wird vom Start eines anderen Laufs nicht gelöscht.
import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { cleanEnv, start, until } from './helpers'

const CFG = path.join('tests', 'ports', 'probe', 'sentinel.config.ts')

test('Lauf B (Start räumt sein outputDir) löscht die Ergebnisse des laufenden Laufs A nicht', async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'fld-outdir-'))
  const ready = path.join(tmp, 'a.ready')
  const go = path.join(tmp, 'a.go')
  const env = (role: string) => cleanEnv({ PROBE_ROLE: role, PROBE_READY: ready, PROBE_GO: go })
  const a = start('npx', ['playwright', 'test', '-c', CFG], env('A'))
  try {
    const dirA = await until(`Lauf A bereit\n${a.out()}`, () => fs.existsSync(ready) && fs.readFileSync(ready, 'utf8'))
    expect(fs.existsSync(path.join(dirA, 'sentinel-A.txt'))).toBe(true)
    const b = start('npx', ['playwright', 'test', '-c', CFG], env('B'))
    expect(await b.exited, `Lauf B:\n${b.out()}`).toBe(0)
    fs.writeFileSync(go, '')
    expect(await a.exited, `Lauf A:\n${a.out()}`).toBe(0)
  } finally {
    fs.writeFileSync(go, '')
    await a.stop()
  }
})
