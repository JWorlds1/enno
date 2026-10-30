import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Schriften selbst gehostet statt Google Fonts: keine Drittanfrage beim Seitenaufruf (DSGVO, LG München 3 O 17493/20)
// und kein Netz nötig — die E2E-Tests laufen im Käfig ohne Internet.
import '@fontsource/open-sans/400.css'
import '@fontsource/open-sans/600.css'
import '@fontsource/open-sans/700.css'
import '@fontsource/montserrat/500.css'
import '@fontsource/montserrat/600.css'
import '@fontsource/montserrat/700.css'
import '@fontsource/montserrat/800.css'
import './theme.css'
import { App } from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
