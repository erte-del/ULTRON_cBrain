import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import OverlayApp from './components/OverlayApp.tsx'

// The Mac app's overlay window loads this same page with ?overlay=1.
const overlay = new URLSearchParams(location.search).has('overlay')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {overlay ? <OverlayApp /> : <App />}
  </StrictMode>,
)
