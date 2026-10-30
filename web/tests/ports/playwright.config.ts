// Eigene Konfiguration für die Abnahmetests der parallelen E2E-Läufe (Lauf r-20261011-e2e-ports-parallel-4).
// Bewusst ohne webServer/globalSetup: geprüft werden Konfiguration und Skripte, nicht die App.
// Aufruf: cd web && npx playwright test -c tests/ports/playwright.config.ts
import { defineConfig } from '@playwright/test'
import os from 'node:os'
import path from 'node:path'

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.ts',
  workers: 1,
  timeout: 120_000,
  retries: 0,
  reporter: [['list']],
  outputDir: path.join(os.tmpdir(), 'fld-e2e-ports-abnahme'),
})
