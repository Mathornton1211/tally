import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { apply, watchSystem } from './lib/theme'
import './index.css'

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } })

// Installed on a phone, Tally should open like an app and survive a dead
// connection long enough to say so. Data still always comes from the server.
if ('serviceWorker' in navigator && location.protocol === 'https:') {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* not fatal */ })
  })
}

apply()
watchSystem()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
