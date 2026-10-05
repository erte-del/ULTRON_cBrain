// The screen overlay: a small always-on-top window (Chrome's Document Picture-in-Picture)
// with a text box and Ultron's answer, plus Ultron's view of your screen.
//
// Window and capture are separate on purpose: ScreenOverlay.tsx knows nothing about
// Picture-in-Picture, and screenSource.ts knows nothing about windows. The Mac overlay
// can reuse both by hosting the same view in a native window and a native ScreenSource.

import { useCallback, useEffect, useRef, useState } from 'react'
import { uploadScreen, type Attachment } from '../ws'
import { BrowserScreenSource, browserCanShareScreen, type ScreenSource } from './screenSource'

interface PipApi {
  requestWindow(options?: { width?: number; height?: number }): Promise<Window>
}
const pipApi = () => (window as unknown as { documentPictureInPicture?: PipApi }).documentPictureInPicture

export const screenOverlaySupported = () => !!pipApi() && browserCanShareScreen()

const SIZE = { width: 400, height: 340 }

// The overlay window starts empty: give it the page's styles.
function copyStyles(win: Window) {
  for (const sheet of Array.from(document.styleSheets)) {
    try {
      const style = win.document.createElement('style')
      style.textContent = Array.from(sheet.cssRules).map((r) => r.cssText).join('\n')
      win.document.head.append(style)
    } catch {
      if (!sheet.href) continue // can't read it and can't link it
      const link = win.document.createElement('link')
      link.rel = 'stylesheet'
      link.href = sheet.href
      win.document.head.append(link)
    }
  }
  win.document.title = 'Ultron'
  win.document.documentElement.className = 'screen-overlay-doc'
}

// Start in the bottom-left corner. Browsers may refuse to move the window: then it stays where it opens.
function placeBottomLeft(win: Window) {
  try {
    const s = window.screen as Screen & { availLeft?: number; availTop?: number }
    win.moveTo((s.availLeft ?? 0) + 16, (s.availTop ?? 0) + s.availHeight - win.outerHeight - 16)
  } catch {
    // stays where the browser put it
  }
}

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function useScreenOverlay(sendText: (text: string, files?: Attachment[]) => boolean) {
  const [win, setWin] = useState<Window | null>(null)
  const [sharing, setSharing] = useState(false)
  const [error, setError] = useState('')
  const winRef = useRef<Window | null>(null)
  const [source] = useState<ScreenSource>(() => {
    const src = new BrowserScreenSource()
    src.onEnded = () => setSharing(false)
    return src
  })

  const close = useCallback(() => {
    source.stop()
    setSharing(false)
    const w = winRef.current
    winRef.current = null
    setWin(null)
    w?.close()
  }, [source])

  /** Pick a screen to share. From the overlay's own button the click is in that window. */
  const share = useCallback(async (from?: Window) => {
    setError('')
    try {
      await source.start(from)
      setSharing(true)
    } catch (e) {
      setSharing(false)
      // Cancelling the picker is not an error worth shouting about.
      if (!(e instanceof DOMException && (e.name === 'NotAllowedError' || e.name === 'AbortError'))) setError(errorText(e))
    }
  }, [source])

  // Call from a click or key press: both the window and the screen picker need one.
  const open = useCallback(async () => {
    if (winRef.current) {
      winRef.current.focus()
      if (!source.active) void share()
      return
    }
    const api = pipApi()
    if (!api) return setError('Your browser can\'t open an overlay window. Use Chrome or Edge.')
    setError('')
    // Both start in the same click. If the browser only allows one per click, the window
    // opens anyway and its "Share my screen" button asks again.
    const picked = share()
    try {
      const w = await api.requestWindow(SIZE)
      copyStyles(w)
      placeBottomLeft(w)
      w.addEventListener('pagehide', close) // closing the overlay also stops sharing
      winRef.current = w
      setWin(w)
    } catch (e) {
      source.stop()
      setSharing(false)
      setError(errorText(e))
    }
    await picked
  }, [close, share, source])

  useEffect(() => () => close(), [close]) // leaving the page ends it all

  /** Send a message from the overlay, with a fresh picture of the screen if asked. */
  const ask = useCallback(async (text: string, withScreen: boolean) => {
    setError('')
    let files: Attachment[] = []
    if (withScreen && source.active) {
      try {
        files = [await uploadScreen(await source.grab())]
      } catch (e) {
        setError(`Couldn't capture the screen: ${errorText(e)}`)
        return false
      }
    }
    return sendText(text, files)
  }, [sendText, source])

  return { win, sharing, error, open, close, share, ask }
}
