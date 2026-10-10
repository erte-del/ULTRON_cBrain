// An ACC track: the layout with braking zones, overtaking spots and numbered corners.
// Data comes from the track card (backend/tools/tracks.py); tap a corner number for its details.

import { useState } from 'react'

interface Corner {
  number: number
  letter?: string
  fraction: number
  direction?: string
  radius_m?: number
  est_min_speed_kmh?: number
  source?: string
}
interface Zone {
  start: number
  end: number
  apex: number
  class: 'heavy' | 'medium' | 'light' | 'lift'
  speed_from_kmh: number
  speed_to_kmh: number
  overtaking_candidate: boolean
}
interface Note {
  text: string
  source: string
}
export interface TrackData {
  id: string
  name: string
  length_m: number
  points: [number, number][]
  numbered_corners: Corner[]
  numbering_status: string
  braking_zones: Zone[]
  notes: Note[]
  estimate_warning: string
  attribution: string
}

const SIZE = 600

function pointAt(points: [number, number][], fraction: number): [number, number] {
  const i = Math.round(fraction * points.length) % points.length
  return points[i]
}

// The part of the lap from fraction a to fraction b (wraps past the start line).
function segment(points: [number, number][], a: number, b: number): [number, number][] {
  const n = points.length
  const from = Math.round(a * n) % n
  const to = Math.round(b * n) % n
  const out: [number, number][] = []
  for (let i = from; i !== to; i = (i + 1) % n) out.push(points[i])
  out.push(points[to])
  return out
}

function toPath(pts: [number, number][], tx: (p: [number, number]) => [number, number]): string {
  return pts
    .map((p, i) => {
      const [x, y] = tx(p)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

const ZONE_COLOUR: Record<string, string> = { heavy: '#e5484d', medium: '#f5a524' }

export default function TrackCard({ data }: { data: TrackData }) {
  const [picked, setPicked] = useState<number | null>(null)
  const pts = data.points
  if (!pts || pts.length < 2) return <div className="card-text">This track has no layout data.</div>

  // Fit the layout into the square, north up (SVG's y points down).
  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => -p[1])
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const pad = 30
  const scale = (SIZE - 2 * pad) / Math.max(maxX - minX, maxY - minY)
  const tx = (p: [number, number]): [number, number] => [
    pad + (p[0] - minX) * scale,
    pad + (-p[1] - minY) * scale,
  ]

  const corner = data.numbered_corners.find((c) => c.number === picked)
  const shown = data.braking_zones.filter((z) => z.class === 'heavy' || z.class === 'medium')
  const heavy = shown.filter((z) => z.class === 'heavy').length
  const overtake = shown.filter((z) => z.overtaking_candidate).length

  return (
    <div className="track-card">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="track-svg" role="img" aria-label={`${data.name} layout`}>
        <path d={toPath(pts, tx) + ' Z'} fill="none" stroke="#9aa4b2" strokeWidth={3} vectorEffect="non-scaling-stroke" />
        {shown.map((z, i) => (
          <path
            key={i}
            d={toPath(segment(pts, z.start, z.end), tx)}
            fill="none"
            stroke={ZONE_COLOUR[z.class]}
            strokeWidth={6}
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {shown
          .filter((z) => z.overtaking_candidate)
          .map((z, i) => {
            const [x, y] = tx(pointAt(pts, z.start))
            return (
              <g key={`o${i}`} transform={`translate(${x},${y})`}>
                <circle r={9} fill="#2fbf71" stroke="#0b0f14" strokeWidth={1.5} />
                <text textAnchor="middle" dominantBaseline="central" fontSize={11} fill="#0b0f14">
                  ★
                </text>
              </g>
            )
          })}
        {(() => {
          const [x, y] = tx(pts[0])
          return <rect x={x - 5} y={y - 5} width={10} height={10} fill="#fff" stroke="#0b0f14" />
        })()}
        {data.numbered_corners.map((c) => {
          const [x, y] = tx(pointAt(pts, c.fraction))
          const on = c.number === picked
          return (
            <g key={`c${c.number}${c.letter ?? ''}`} transform={`translate(${x},${y})`} className="track-corner" onClick={() => setPicked(c.number)}>
              <circle r={on ? 12 : 10} fill={on ? '#4a8cff' : '#1b2430'} stroke="#e6edf3" strokeWidth={1.5} />
              <text textAnchor="middle" dominantBaseline="central" fontSize={10} fontWeight={700} fill="#e6edf3">
                {c.number}
                {c.letter ?? ''}
              </text>
            </g>
          )
        })}
      </svg>

      <div className="track-legend">
        <span><i style={{ background: ZONE_COLOUR.heavy }} /> heavy braking ({heavy})</span>
        <span><i style={{ background: ZONE_COLOUR.medium }} /> medium braking</span>
        <span><i style={{ background: '#2fbf71' }} /> overtaking spot ({overtake})</span>
        <span>Length {(data.length_m / 1000).toFixed(3)} km</span>
      </div>

      {corner ? (
        <div className="track-detail">
          <strong>Corner {corner.number}{corner.letter ?? ''}</strong>
          <div>
            {corner.direction ? `${corner.direction}-hander` : 'Direction not known'}
            {corner.radius_m ? `, radius about ${corner.radius_m} m` : ''}
            {corner.est_min_speed_kmh ? `, about ${corner.est_min_speed_kmh} km/h at its slowest (estimate)` : ''}
          </div>
          {shown
            .filter((z) => Math.abs(z.apex - corner.fraction) < 0.01 || Math.abs(z.end - corner.fraction) < 0.01)
            .map((z, i) => (
              <div key={i}>
                {z.class} braking, {z.speed_from_kmh} → {z.speed_to_kmh} km/h
                {z.overtaking_candidate ? ' · overtaking spot' : ''}
              </div>
            ))}
        </div>
      ) : (
        <div className="track-hint">Tap a corner number for its details.</div>
      )}

      <div className="track-foot">
        {data.numbering_status && <div>Corner numbers: {data.numbering_status}</div>}
        <div>{data.estimate_warning}</div>
        {data.notes.map((n, i) => (
          <div key={i}>
            Guide: {n.text} (<a href={n.source} target="_blank" rel="noreferrer">source</a>)
          </div>
        ))}
        <div className="track-attr">{data.attribution}</div>
      </div>
    </div>
  )
}
