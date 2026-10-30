import { defineConfig } from '@playwright/test'
import { allocatePortsSync } from './e2e/ports'

// Ports: aus der Umgebung (festgelegt), sonst frei vergeben. Zurück in process.env, damit Worker,
// globalSetup und Tests (laden die Konfiguration erneut) dieselben Ports sehen.
const free = process.env.FLD_E2E_BACKEND_PORT && process.env.FLD_E2E_VITE_PORT ? null : allocatePortsSync()
const backend = process.env.FLD_E2E_BACKEND_PORT || String(free!.backend)
const vite = process.env.FLD_E2E_VITE_PORT || String(free!.vite)
process.env.FLD_E2E_BACKEND_PORT = backend
process.env.FLD_E2E_VITE_PORT = vite

// End-to-End: echter Browser (installiertes Chrome) → Vite-Proxy → FastAPI → Engine/DB.
// Ein Worker: die MILP-Rechnungen sind CPU-gebunden und /plant-config ist geteilter Zustand.
export default defineConfig({
  testDir: './e2e',
  // je Lauf eigener Ergebnisordner (aus dem Vite-Port, den Worker beim erneuten Laden wieder sehen)
  outputDir: `test-results/run-${vite}`,
  globalSetup: './e2e/global-setup.ts',
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 45_000 },
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${vite}`,
    channel: 'chrome',
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'cd .. && ./run-backend.sh',
      url: `http://127.0.0.1:${backend}/api/v1/health`,
      env: { FLD_PORT: backend },
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      url: `http://localhost:${vite}`,
      env: { FLD_WEB_PORT: vite, FLD_API_URL: `http://127.0.0.1:${backend}` },
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})
