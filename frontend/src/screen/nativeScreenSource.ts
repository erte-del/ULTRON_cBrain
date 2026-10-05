// Screen source for the Mac app (scripts/Ultron.swift): the app owns the capture
// (ScreenCaptureKit) and the overlay window, and this page talks to it through a small
// bridge. Same ScreenSource interface as the browser version, so ScreenOverlayView and
// uploadScreen don't change.

import type { ScreenSource } from './screenSource'

interface Bridge { postMessage(message: { type: 'start' | 'grab' | 'hide' }): Promise<unknown> }
const bridge = (): Bridge | undefined =>
  (window as unknown as { webkit?: { messageHandlers?: { ultron?: Bridge } } }).webkit?.messageHandlers?.ultron

/** True inside the Mac app's overlay window. */
export const insideMacApp = () => !!bridge()

export class NativeScreenSource implements ScreenSource {
  onEnded: (() => void) | null = null
  active = false

  async start() {
    // Asks macOS for Screen Recording permission the first time; throws until it's given.
    await bridge()!.postMessage({ type: 'start' })
    this.active = true
  }

  async grab(): Promise<Blob> {
    if (!this.active) throw new Error('Not allowed to see the screen yet')
    const base64 = await bridge()!.postMessage({ type: 'grab' })
    const bytes = Uint8Array.from(atob(String(base64)), (c) => c.charCodeAt(0))
    return new Blob([bytes], { type: 'image/jpeg' })
  }

  stop() {
    this.active = false // macOS keeps the permission; we just stop asking for pictures
  }

  /** Hide the overlay window (the Mac app keeps running). */
  hide() {
    void bridge()?.postMessage({ type: 'hide' })
  }
}
