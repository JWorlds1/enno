// Hilfs-Konfiguration: lädt die ECHTE web/playwright.config.ts in einem eigenen Playwright-Prozess und meldet,
// was sie festlegt (Ports, webServer-Umgebung, outputDir). Wird von den Abnahmetests als Kindprozess gestartet.
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: 'config.probe.ts',
  workers: 1,
  timeout: 90_000,
  reporter: 'line',
  outputDir: process.env.PROBE_TMP,
})
