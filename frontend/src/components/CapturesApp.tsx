// The capture library (http://127.0.0.1:8000/?captures=1): your recordings and clips by date,
// a player with a trim bar, rename, favourite, download and delete. Talks to /api/captures.

import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE } from '../ws'

interface Item {
  id: string
  title: string
  created: number
  seconds: number
  fav: boolean
  url: string
  thumb: string
}
type Mode = 'off' | 'buffer' | 'recording'

const post = (path: string, body: object = {}) =>
  fetch(API_BASE + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const day = (t: number) => new Date(t * 1000).toLocaleDateString(undefined, { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' })

function Player({ item, onClose, onChange }: { item: Item; onClose: () => void; onChange: () => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const [range, setRange] = useState<[number, number]>([0, item.seconds])
  const [title, setTitle] = useState(item.title)
  const [busy, setBusy] = useState(false)
  const [start, end] = range
  const trimmed = start > 0.1 || end < item.seconds - 0.1

  const mark = (which: 0 | 1) => {
    const t = video.current?.currentTime ?? 0
    setRange(which === 0 ? [Math.min(t, end - 0.5), end] : [start, Math.max(t, start + 0.5)])
  }
  const seek = (t: number) => video.current && (video.current.currentTime = t)
  const save = async () => {
    setBusy(true)
    await post(`/api/captures/${item.id}/clip`, { start, end })
    setBusy(false)
    onChange()
    onClose()
  }
  const rename = async () => title.trim() && title !== item.title && (await post(`/api/captures/${item.id}`, { title }), onChange())
  const remove = async () => {
    if (!confirm(`Delete “${item.title}”? This can't be undone.`)) return
    await post(`/api/captures/${item.id}/delete`)
    onChange()
    onClose()
  }

  return (
    <div className="cap-player">
      <div className="cap-bar">
        <button type="button" onClick={onClose}>← Library</button>
        <input value={title} onChange={(e) => setTitle(e.target.value)} onBlur={rename} aria-label="Title" />
        <button type="button" onClick={async () => (await post(`/api/captures/${item.id}`, { fav: !item.fav }), onChange())}>
          {item.fav ? '★' : '☆'}
        </button>
        <a href={`${API_BASE}${item.url}?download=1`} download>↓ Download</a>
        <button type="button" className="danger" onClick={remove}>Delete</button>
      </div>
      <video ref={video} src={API_BASE + item.url} controls autoPlay playsInline />
      <div className="cap-trim">
        <button type="button" onClick={() => mark(0)}>[ Set start</button>
        <input type="range" min={0} max={item.seconds} step={0.1} value={start} aria-label="Clip start"
               onChange={(e) => { const v = Math.min(+e.target.value, end - 0.5); setRange([v, end]); seek(v) }} />
        <input type="range" min={0} max={item.seconds} step={0.1} value={end} aria-label="Clip end"
               onChange={(e) => { const v = Math.max(+e.target.value, start + 0.5); setRange([start, v]); seek(v) }} />
        <button type="button" onClick={() => mark(1)}>Set end ]</button>
        <span>{clock(start)} – {clock(end)} ({(end - start).toFixed(1)} s)</span>
        <button type="button" className="primary" disabled={!trimmed || busy} onClick={save}>
          {busy ? 'Saving…' : 'Save as new clip'}
        </button>
      </div>
    </div>
  )
}

export default function CapturesApp() {
  const [items, setItems] = useState<Item[]>([])
  const [mode, setMode] = useState<Mode>('off')
  const [query, setQuery] = useState('')
  const [favs, setFavs] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await (await fetch(`${API_BASE}/api/captures`)).json()
      setItems(data.items)
      setMode(data.mode)
      setError('')
    } catch {
      setError('Ultron isn’t running.')
    }
  }, [])
  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [load])

  const recorder = async (action: 'record' | 'buffer' | 'stop') => {
    const res = await post('/api/captures/recorder', { action })
    if (!res.ok) setError('That didn’t work. Is ffmpeg installed?')
    load()
  }

  const shown = items.filter((i) => i.title.toLowerCase().includes(query.toLowerCase()) && (!favs || i.fav))
  const days = [...new Set(shown.map((i) => day(i.created)))]
  const current = items.find((i) => i.id === open)

  return (
    <div className="captures">
      {current ? (
        <Player item={current} onClose={() => setOpen(null)} onChange={load} />
      ) : (
        <>
          <div className="cap-bar">
            <h1>Captures</h1>
            <input placeholder="Search" value={query} onChange={(e) => setQuery(e.target.value)} />
            <button type="button" className={favs ? 'on' : ''} onClick={() => setFavs(!favs)}>★ Favourites</button>
            <span className="spacer" />
            {mode === 'off' ? (
              <>
                <button type="button" className="primary" onClick={() => recorder('record')}>● Record</button>
                <button type="button" onClick={() => recorder('buffer')}>Start replay buffer</button>
              </>
            ) : (
              <button type="button" className="danger" onClick={() => recorder('stop')}>
                ■ Stop {mode === 'recording' ? 'recording' : 'replay buffer'}
              </button>
            )}
          </div>
          {error && <p className="cap-error">{error}</p>}
          {!items.length && !error && <p className="cap-empty">Nothing here yet. Press Record, or ask Ultron to “start capturing”.</p>}
          {days.map((d) => (
            <section key={d}>
              <h2>{d}</h2>
              <div className="cap-grid">
                {shown.filter((i) => day(i.created) === d).map((i) => (
                  <button type="button" key={i.id} className="cap-tile" onClick={() => setOpen(i.id)}>
                    <img src={API_BASE + i.thumb} alt="" loading="lazy" />
                    <span className="cap-len">{clock(i.seconds)}</span>
                    <span className="cap-title">{i.fav && '★ '}{i.title}</span>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </>
      )}
    </div>
  )
}
