// Wie die echte Konfiguration (inkl. outputDir, so aufgelöst wie dort relativ zu web/), aber ohne Server und Vorwärmen.
import { defineConfig } from '@playwright/test'
import path from 'node:path'
import real from '../../../playwright.config'

const web = path.resolve(__dirname, '../../..')

export default defineConfig({
  ...real,
  testDir: '.',
  testMatch: 'sentinel.probe.ts',
  globalSetup: undefined,
  webServer: undefined,
  reporter: 'line',
  workers: 1,
  timeout: 90_000,
  outputDir: path.resolve(web, real.outputDir ?? 'test-results'),
})
