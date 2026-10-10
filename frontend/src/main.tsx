import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import CapturesApp from './components/CapturesApp.tsx'
import OverlayApp from './components/OverlayApp.tsx'

// The Mac app's overlay window loads this same page with ?overlay=1.
const params = new URLSearchParams(location.search)
const overlay = params.has('overlay')
const captures = params.has('captures') // the clipping library

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {captures ? <CapturesApp /> : overlay ? <OverlayApp /> : <App />}
  </StrictMode>,
)
