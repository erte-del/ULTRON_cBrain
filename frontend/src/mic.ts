// The microphone in voice mode: 100 ms chunks of 16 kHz, 16-bit mono PCM for the server's
// speech detector (backend/voice/vad.py), and how loud you are, for the orb.

// Runs on the browser's audio thread. Averages the mic's samples (usually 48 kHz) down to
// 16 kHz, which also takes out the high sounds that would otherwise fold into speech.
const WORKLET = `
class UltronMic extends AudioWorkletProcessor {
  constructor() {
    super()
    this.step = sampleRate / 16000
    this.t = 0; this.sum = 0; this.count = 0; this.peak = 0
    this.out = new Int16Array(1600); this.n = 0
  }
  process([input]) {
    for (const s of input[0] || []) {
      this.sum += s; this.count++
      if (++this.t < this.step) continue
      this.t -= this.step
      const v = Math.max(-1, Math.min(1, this.sum / this.count))
      this.sum = this.count = 0
      this.peak = Math.max(this.peak, Math.abs(v))
      this.out[this.n++] = v * 32767
      if (this.n < this.out.length) continue
      this.port.postMessage({ pcm: this.out.buffer, level: this.peak }, [this.out.buffer])
      this.out = new Int16Array(1600); this.n = 0; this.peak = 0
    }
    return true
  }
}
registerProcessor('ultron-mic', UltronMic)
`

/** Starts the mic (the browser asks the first time). Resolves to a function that stops it. */
export async function startMic(onChunk: (pcm: ArrayBuffer, level: number) => void): Promise<() => void> {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('This page can’t use the microphone (it needs https or this Mac).')
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  })
  const ctx = new AudioContext()
  const stop = () => {
    stream.getTracks().forEach((t) => t.stop())
    void ctx.close()
  }
  try {
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'text/javascript' }))
    try {
      await ctx.audioWorklet.addModule(url)
    } finally {
      URL.revokeObjectURL(url)
    }
    if (ctx.state !== 'running') {
      // Started without a click (the page opened with "Hey Ultron" on): the browser may hold
      // the sound back until you click or type on the page once.
      void ctx.resume()
      const allow = () => void ctx.resume()
      document.addEventListener('pointerdown', allow, { once: true })
      document.addEventListener('keydown', allow, { once: true })
    }
    const node = new AudioWorkletNode(ctx, 'ultron-mic', { numberOfOutputs: 0 }) // a sink: always runs
    node.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; level: number }>) => onChunk(e.data.pcm, e.data.level)
    ctx.createMediaStreamSource(stream).connect(node)
  } catch (e) {
    stop()
    throw e
  }
  return stop
}
