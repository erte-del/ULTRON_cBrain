// The reactor core in the middle of the HUD. It is also the voice orb: its rings
// show what Ultron is doing (idle / listening / thinking / speaking). (Phase 5)

import { useEffect, useRef } from 'react'

export type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking'

const CORE_TEXT: Record<VoiceState, [string, string]> = {
  idle: ['CORE', 'ACTIVE'],
  listening: ['VOICE', 'INPUT'],
  thinking: ['CORE', 'BUSY'],
  speaking: ['VOICE', 'OUTPUT'],
}

// The orb: a sphere of glowing points joined by faint lines, drawn on a canvas.
// It turns slowly when idle, faster while thinking, and pulses and loosens while speaking.
const N = 650
const LINK = 0.26 // points closer than this (unit sphere) may get a line
const SPEED: Record<VoiceState, number> = { idle: 0.12, listening: 0.2, thinking: 0.9, speaking: 0.25 }

// Seeded random, so the orb looks the same every load.
let seed = 7
const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)

// Points on a unit sphere (Fibonacci spiral), then broken up: a few patches are torn
// out, the rest sit in a thick shell, and some shards drift loose.
const GAPS = Array.from({ length: 4 }, () => {
  const z = rnd() * 2 - 1
  const a = rnd() * Math.PI * 2
  const r = Math.sqrt(1 - z * z)
  return { c: [Math.cos(a) * r, z, Math.sin(a) * r], w: 0.2 + rnd() * 0.15 }
})
const POINTS: (readonly [number, number, number])[] = []
for (let i = 0; i < N; i++) {
  const y = 1 - (2 * (i + 0.5)) / N
  const r0 = Math.sqrt(1 - y * y)
  const a = i * Math.PI * (3 - Math.sqrt(5))
  const x = Math.cos(a) * r0
  const z = Math.sin(a) * r0
  if (GAPS.some((g) => Math.hypot(x - g.c[0], y - g.c[1], z - g.c[2]) < g.w) && rnd() < 0.7) continue
  const k = rnd() < 0.08 ? 1.15 + rnd() * 0.5 : 0.93 + rnd() * 0.14 // a thick shell, 8% loose dust
  POINTS.push([x * k, y * k, z * k])
}
for (let i = 0; i < 25; i++) POINTS.push([(rnd() - 0.5) * 1.3, (rnd() - 0.5) * 1.3, (rnd() - 0.5) * 1.3]) // sparse inside

// Every point wanders a little on its own loop, and points in the same clump drift
// together. Links are made and broken by the distance between points.
const CLUMPS = Array.from({ length: 6 }, () => ({
  c: [rnd() * 2 - 1, rnd() * 2 - 1, rnd() * 2 - 1],
  f: [0.1 + rnd() * 0.25, 0.1 + rnd() * 0.25, 0.1 + rnd() * 0.25],
  p: [rnd() * 6.3, rnd() * 6.3, rnd() * 6.3],
}))
const MOTION = POINTS.map((p) => {
  let clump = 0
  let best = 9
  CLUMPS.forEach((k, i) => {
    const d = Math.hypot(p[0] - k.c[0], p[1] - k.c[1], p[2] - k.c[2])
    if (d < best) [best, clump] = [d, i]
  })
  return { clump, out: 0.4 + rnd() * 1.2, f: [0.2 + rnd() * 0.5, 0.2 + rnd() * 0.5, 0.2 + rnd() * 0.5], p: [rnd() * 6.3, rnd() * 6.3, rnd() * 6.3] }
})
const EDGES: [number, number][] = []
POINTS.forEach((p, i) => {
  for (let j = i + 1; j < POINTS.length; j++) {
    const d = Math.hypot(p[0] - POINTS[j][0], p[1] - POINTS[j][1], p[2] - POINTS[j][2])
    if (d < LINK * 1.4 && rnd() < 0.3) EDGES.push([i, j])
  }
})
const FLICKER = POINTS.map(() => rnd() * 1000)

interface VoiceOrbProps {
  state: VoiceState
  level?: number // 0..1, how loud you are (listening) or Ultron is (speaking)
  onClick?: () => void
  label: string
}

export default function VoiceOrb({ state, level = 0, onClick, label }: VoiceOrbProps) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const live = useRef({ state, level })
  live.current = { state, level }
  const [line1, line2] = CORE_TEXT[state]

  useEffect(() => {
    const el = canvas.current
    const ctx = el?.getContext('2d')
    if (!el || !ctx) return
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let angle = 0
    let speed = SPEED.idle
    let loose = 0 // 0 = tight shape, 1 = speaking: nodes pulse outward and fall back
    let last = performance.now()
    let raf = 0

    const frame = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      const { state: st, level: lv } = live.current
      speed += (SPEED[st] - speed) * Math.min(dt * 2, 1) // ease between speeds
      if (!still) angle += speed * dt
      loose += ((st === 'speaking' && !still ? 1 : 0) - loose) * Math.min(dt * 3, 1)
      const beat = 0.5 + 0.5 * Math.sin(now / 360) // nodes go out and come back
      const slow = 0.5 + 0.5 * Math.sin(now / 800) // the whole orb swells slower and less
      const spread = loose * beat * (0.22 + 0.3 * lv)

      const size = el.clientWidth
      const dpr = window.devicePixelRatio || 1
      if (el.width !== size * dpr) el.width = el.height = size * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, size, size)

      const pulse = 1 + loose * (0.012 * slow + 0.02 * lv)
      const breathe = 1 + 0.015 * Math.sin(now / 1500)
      const R = size * 0.3 * pulse * breathe
      const cx = size / 2
      const tilt = 0.35
      const [ca, sa, ct, stl] = [Math.cos(angle), Math.sin(angle), Math.cos(tilt), Math.sin(tilt)]
      const t = (now / 1000) * (0.4 + speed) // drift quickens when thinking
      const pts = POINTS.map(([px, py, pz], i) => {
        const m = MOTION[i]
        const k = CLUMPS[m.clump]
        const o = 1 + spread * m.out // each node flies out by its own amount
        const x = px * o + 0.07 * Math.sin(t * k.f[0] + k.p[0]) + 0.035 * Math.sin(t * m.f[0] + m.p[0])
        const y = py * o + 0.07 * Math.sin(t * k.f[1] + k.p[1]) + 0.035 * Math.sin(t * m.f[1] + m.p[1])
        const z = pz * o + 0.07 * Math.sin(t * k.f[2] + k.p[2]) + 0.035 * Math.sin(t * m.f[2] + m.p[2])
        const x1 = x * ca + z * sa
        const z1 = -x * sa + z * ca
        const y1 = y * ct - z1 * stl
        const z2 = y * stl + z1 * ct
        return [cx + x1 * R, cx + y1 * R, z2] as const // z2: -1 far .. 1 near
      })

      ctx.lineWidth = 0.7
      const reach = (R * LINK * 1.3) ** 2
      for (const [i, j] of EDGES) {
        const d2 = (pts[i][0] - pts[j][0]) ** 2 + (pts[i][1] - pts[j][1]) ** 2
        if (d2 > reach) continue // too far apart now: the link breaks
        const near = 1 - d2 / reach
        const depth = (pts[i][2] + pts[j][2]) / 2
        ctx.strokeStyle = `rgba(192, 132, 252, ${near * (0.06 + 0.3 * (depth + 1) / 2)})`
        ctx.beginPath()
        ctx.moveTo(pts[i][0], pts[i][1])
        ctx.lineTo(pts[j][0], pts[j][1])
        ctx.stroke()
      }
      pts.forEach(([x, y, z], i) => {
        const t = Math.max(0, Math.min(1, (z + 1) / 2)) // loose dust can sit beyond the sphere: keep the radius positive
        const f = 0.65 + 0.35 * Math.sin(now / 280 + FLICKER[i]) // each point twinkles
        ctx.fillStyle = `rgba(233, 213, 255, ${(0.2 + 0.8 * t) * f})`
        ctx.beginPath()
        ctx.arc(x, y, (0.6 + 1.9 * t) * (i % 9 === 0 ? 1.6 : 1), 0, Math.PI * 2)
        ctx.fill()
      })
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [])

  return (
    <button type="button" className={`reactor reactor-${state}`} onClick={onClick} aria-label={label} title={label}>
      <canvas ref={canvas} aria-hidden="true" />
      <span className="r-label">
        {line1}
        <br />
        {line2}
      </span>
    </button>
  )
}
