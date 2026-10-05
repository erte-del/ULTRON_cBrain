// Where Ultron's view of your screen comes from.
//
// The overlay only talks to this interface, so the capture can be swapped. Today it's the
// browser's screen share (BrowserScreenSource). The planned Mac overlay would implement the
// same three calls with ScreenCaptureKit, and post what grab() returns to POST /screen.

export interface ScreenSource {
  /** Ask the user what to share and start looking. `win`: the window whose click asked for it. */
  start(win?: Window): Promise<void>
  /** One JPEG of the screen as it is right now. */
  grab(): Promise<Blob>
  /** Stop looking and release the screen. */
  stop(): void
  /** The user stopped sharing from outside (the browser's "Stop sharing" bar). */
  onEnded: (() => void) | null
  readonly active: boolean
}

const MAX_PX = 1920 // long side of what we send; the backend shrinks it again for Claude
const QUALITY = 0.85

// ImageCapture isn't in TypeScript's DOM types yet (Chrome and Edge have it).
interface ImageCaptureLike { grabFrame(): Promise<ImageBitmap> }
declare const ImageCapture: (new (track: MediaStreamTrack) => ImageCaptureLike) | undefined

export const browserCanShareScreen = () => !!navigator.mediaDevices?.getDisplayMedia

export class BrowserScreenSource implements ScreenSource {
  onEnded: (() => void) | null = null
  private stream: MediaStream | null = null
  private track: MediaStreamTrack | null = null
  private capture: ImageCaptureLike | null = null
  private video: HTMLVideoElement | null = null

  get active() {
    return this.track?.readyState === 'live'
  }

  async start(win: Window = window) {
    this.stop()
    // "monitor" asks for the whole screen, which is what keeps working when you switch tabs.
    const options = {
      video: { displaySurface: 'monitor', frameRate: 5 },
      audio: false,
      selfBrowserSurface: 'exclude',
      surfaceSwitching: 'include',
    } as DisplayMediaStreamOptions
    const stream = await win.navigator.mediaDevices.getDisplayMedia(options)
    const track = stream.getVideoTracks()[0]
    this.stream = stream
    this.track = track
    track.addEventListener('ended', () => {
      this.release()
      this.onEnded?.()
    })
    if (typeof ImageCapture !== 'undefined') {
      this.capture = new ImageCapture(track)
    } else {
      // No ImageCapture (Firefox, Safari): read frames from a hidden video instead.
      const video = document.createElement('video')
      video.muted = true
      video.srcObject = stream
      await video.play()
      this.video = video
    }
  }

  async grab(): Promise<Blob> {
    if (!this.active) throw new Error('Not sharing the screen')
    const frame: ImageBitmap | HTMLVideoElement = this.capture ? await this.capture.grabFrame() : this.video!
    const w = frame instanceof HTMLVideoElement ? frame.videoWidth : frame.width
    const h = frame instanceof HTMLVideoElement ? frame.videoHeight : frame.height
    if (!w || !h) throw new Error('The screen has no picture yet')
    const scale = Math.min(1, MAX_PX / Math.max(w, h))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(w * scale)
    canvas.height = Math.round(h * scale)
    canvas.getContext('2d')!.drawImage(frame, 0, 0, canvas.width, canvas.height)
    if (!(frame instanceof HTMLVideoElement)) frame.close()
    return new Promise((resolve, reject) =>
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not capture the screen'))), 'image/jpeg', QUALITY),
    )
  }

  stop() {
    this.stream?.getTracks().forEach((t) => t.stop())
    this.release()
  }

  private release() {
    this.stream = this.track = this.capture = null
    if (this.video) this.video.srcObject = null
    this.video = null
  }
}
