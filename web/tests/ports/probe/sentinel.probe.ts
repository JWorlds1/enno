import { test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const wait = async (file: string, ms = 40_000) => {
  const t0 = Date.now()
  while (!fs.existsSync(file)) {
    if (Date.now() - t0 > ms) throw new Error(`wartete vergeblich auf ${file}`)
    await new Promise((r) => setTimeout(r, 100))
  }
}

test('Lauf schreibt Ergebnisdatei; A prüft, dass B sie nicht löscht', async ({}, testInfo) => {
  const dir = testInfo.project.outputDir
  fs.mkdirSync(dir, { recursive: true })
  const sentinel = path.join(dir, `sentinel-${process.env.PROBE_ROLE}.txt`)
  fs.writeFileSync(sentinel, 'Spur von ' + process.env.PROBE_ROLE)
  if (process.env.PROBE_ROLE !== 'A') return
  fs.writeFileSync(process.env.PROBE_READY!, dir)
  await wait(process.env.PROBE_GO!)
  if (!fs.existsSync(sentinel)) throw new Error(`Ergebnisse von Lauf A wurden von Lauf B gelöscht: ${sentinel}`)
})
