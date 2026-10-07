// Ultron's voice in voice mode: plays the reply's sentences (voice.audio) one after another,
// and stops at once when you click the orb or talk over it. A sentence without audio (the
// server couldn't make the voice) is read by the browser's own voice instead.

type Listener = () => void

function bytes(b64: string): ArrayBuffer {
  const s = atob(b64)
  const out = new Uint8Array(s.length)
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i)
  return out.buffer
}

class Speaker {
  speaking = false
  level = 0 // 0..1, how loud Ultron is right now (the orb)
  private ctx: AudioContext | null = null
  private gain: GainNode | null = null
  private analyser: AnalyserNode | null = null
  private playing = new Set<AudioBufferSourceNode>()
  private browserVoice = 0 // sentences the browser is reading
  private endsAt = 0 // when the queued audio runs out (AudioContext time)
  private queue: Promise<void> = Promise.resolve()
  private round = 0 // bumped by stop(): sentences from before it are dropped
  private listeners = new Set<Listener>()

  subscribe = (fn: Listener) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  private context() {
    if (!this.ctx) {
      this.ctx = new AudioContext()
      this.gain = this.ctx.createGain()
      this.analyser = this.ctx.createAnalyser()
      this.analyser.fftSize = 512
      this.gain.connect(this.analyser).connect(this.ctx.destination)
    }
    void this.ctx.resume()
    return this.ctx
  }

  private update() {
    const now = this.playing.size > 0 || this.browserVoice > 0
    if (now === this.speaking) return
    this.speaking = now
    if (now) this.meter()
    else this.level = 0
    this.listeners.forEach((fn) => fn())
  }

  // While it speaks: how loud, for the orb.
  private meter() {
    const data = new Uint8Array(this.analyser?.fftSize ?? 0)
    const tick = () => {
      if (!this.speaking) return
      if (this.analyser && this.playing.size) {
        this.analyser.getByteTimeDomainData(data)
        let sum = 0
        for (const v of data) sum += ((v - 128) / 128) ** 2
        this.level = Math.min(1, Math.sqrt(sum / data.length) * 4)
      } else this.level = 0.3 // the browser's voice can't be measured
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }

  /** Call from a click (voice mode starting) so the browser lets it play sound later. */
  unlock() {
    this.context()
  }

  play(text: string, audio: string | null) {
    const round = this.round
    this.queue = this.queue.then(async () => {
      if (round !== this.round) return
      if (!audio) {
        const say = new SpeechSynthesisUtterance(text)
        this.browserVoice++
        say.onend = say.onerror = () => {
          this.browserVoice = Math.max(0, this.browserVoice - 1)
          this.update()
        }
        speechSynthesis.speak(say)
        this.update()
        return
      }
      const ctx = this.context()
      const buffer = await ctx.decodeAudioData(bytes(audio)).catch(() => null)
      if (!buffer || round !== this.round) return
      const source = ctx.createBufferSource()
      source.buffer = buffer
      source.connect(this.gain!)
      const at = Math.max(ctx.currentTime + 0.05, this.endsAt)
      source.start(at)
      this.endsAt = at + buffer.duration
      this.playing.add(source)
      source.onended = () => {
        this.playing.delete(source)
        this.update()
      }
      this.update()
    })
  }

  /** Quieter while you might be talking over it; back to normal if you weren't. */
  duck(on: boolean) {
    if (this.ctx && this.gain) this.gain.gain.setTargetAtTime(on ? 0.3 : 1, this.ctx.currentTime, 0.05)
  }

  stop() {
    this.round++
    this.playing.forEach((s) => s.stop())
    this.playing.clear()
    this.endsAt = 0
    this.browserVoice = 0
    speechSynthesis.cancel()
    this.duck(false)
    this.update()
  }
}

export const speaker = new Speaker()
