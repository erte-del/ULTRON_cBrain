// Canvas: images, 3D objects and cards. (Phase 4a)
// Shown in the centre panel: the cards tab (text, table, email list, events, tasks, maps, YouTube, images),
// or one 3D model per tab. The tabs themselves are in Stage.tsx.

import { lazy, Suspense, useState } from 'react'
import type { CanvasCard, ImageCardData, ImageSelection, Model3DData, VideoCardData } from '../ws'
import ImageViewer from './ImageViewer'
import Markdown from './Markdown'
import VideoCard from './VideoCard'
import TrackCard, { type TrackData } from './TrackCard'

// three.js is big: only load the 3D viewer when a 3D model first appears.
const Model3DViewer = lazy(() => import('./Model3DViewer'))
interface CanvasProps {
  cards: CanvasCard[]
  onClose: (id: string) => void
  selectedImage: ImageSelection | null
  onSelectImage: (selection: ImageSelection | null) => void
  tab: string // 'cards' or a 3D model's id
}

function TableCard({ data }: { data: Record<string, unknown> }) {
  const columns = (data.columns as string[]) ?? []
  const rows = (data.rows as string[][]) ?? []
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th key={i}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              {row.map((cell, c) => (
                <td key={c}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

type Item = Record<string, string>

const isUnread = (v?: string) => v === 'true' || v === 'True' || v === '1'

function EmailList({ items }: { items: Item[] }) {
  return (
    <ul className="email-list">
      {items.map((m, i) => (
        <li key={m.id ?? i} className={isUnread(m.unread) ? 'unread' : undefined}>
          <div className="email-top">
            <span className="email-from">{m.from}</span>
            <span className="email-date">{m.date}</span>
          </div>
          <div className="email-subject">{m.subject || '(no subject)'}</div>
          {m.snippet && <div className="email-snippet">{m.snippet}</div>}
        </li>
      ))}
    </ul>
  )
}

function Events({ items }: { items: Item[] }) {
  return (
    <ul className="event-list">
      {items.map((e, i) => (
        <li key={i}>
          <div className="event-when">
            {e.start}
            {e.end && <> – {e.end}</>}
          </div>
          <div className="event-title">{e.title}</div>
          {e.location && <div className="event-meta">{e.location}</div>}
          {e.attendees && <div className="event-meta">With {e.attendees}</div>}
          {e.notes && <div className="event-meta">{e.notes}</div>}
        </li>
      ))}
    </ul>
  )
}

function Tasks({ items }: { items: Item[] }) {
  return (
    <ul className="event-list task-list">
      {items.map((t, i) => (
        <li key={i} className={isUnread(t.done) ? 'done' : undefined}>
          <div className="event-title">
            {isUnread(t.done) ? '☑' : '☐'} {t.title}
          </div>
          {(t.due || t.list) && <div className="event-meta">{[t.due, t.list].filter(Boolean).join(' · ')}</div>}
          {t.notes && <div className="event-meta">{t.notes}</div>}
        </li>
      ))}
    </ul>
  )
}

// Google Maps' embed, built by the backend (tools/canvas.py); nothing else is ever framed.
function MapCard({ data }: { data: Record<string, unknown> }) {
  const url = String(data.url ?? '')
  if (!url.startsWith('https://www.google.com/maps?')) return null
  return (
    <div className="map-card">
      <iframe className="map-frame" src={url} title="Map" loading="lazy" allowFullScreen referrerPolicy="no-referrer-when-downgrade" />
      <a className="map-link" href={String(data.link ?? url)} target="_blank" rel="noreferrer">
        Open in Google Maps ↗
      </a>
    </div>
  )
}

// YouTube's own player for the picked video, and the other results to click. Only ids are
// taken from the card (checked again here), so nothing but YouTube's player is ever framed.
function YoutubeCard({ items }: { items: Item[] }) {
  const videos = items.filter((v) => /^[\w-]{11}$/.test(String(v.id)))
  const [playing, setPlaying] = useState(0)
  const [clicked, setClicked] = useState(false)
  const current = videos[playing]
  if (!current) return null
  return (
    <div className="youtube-card">
      <iframe
        className="youtube-frame"
        src={`https://www.youtube-nocookie.com/embed/${current.id}${clicked ? '?autoplay=1' : ''}`}
        title={String(current.title ?? 'YouTube video')}
        allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
        allowFullScreen
      />
      <ul className="youtube-list">
        {videos.map((v, i) => (
          <li key={String(v.id)}>
            <button
              className={i === playing ? 'youtube-item active' : 'youtube-item'}
              onClick={() => {
                setPlaying(i)
                setClicked(true)
              }}
            >
              <img src={`https://i.ytimg.com/vi/${v.id}/mqdefault.jpg`} alt="" loading="lazy" />
              <span>
                <strong>{v.title}</strong>
                <small>{[v.channel, v.length, v.views, v.age].filter(Boolean).join(' · ')}</small>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function CardBody({
  card,
  selectedImage,
  onSelectImage,
}: { card: CanvasCard } & Pick<CanvasProps, 'selectedImage' | 'onSelectImage'>) {
  switch (card.kind) {
    case 'image':
      return (
        <ImageViewer
          data={card.data as unknown as ImageCardData}
          selected={selectedImage}
          onSelect={onSelectImage}
        />
      )
    case 'video':
      return <VideoCard data={card.data as unknown as VideoCardData} />
    case 'text':
      return (
        <div className="card-text">
          <Markdown text={String(card.data.content ?? '')} />
        </div>
      )
    case 'table':
      return <TableCard data={card.data} />
    case 'email_list':
      return <EmailList items={(card.data.items as Item[]) ?? []} />
    case 'events':
      return <Events items={(card.data.items as Item[]) ?? []} />
    case 'tasks':
      return <Tasks items={(card.data.items as Item[]) ?? []} />
    case 'map':
      return <MapCard data={card.data} />
    case 'youtube':
      return <YoutubeCard items={(card.data.items as Item[]) ?? []} />
    case 'track':
      return <TrackCard data={card.data as unknown as TrackData} />
    default:
      return <pre className="card-raw">{JSON.stringify(card.data, null, 2)}</pre>
  }
}

export default function Canvas({ cards, onClose, selectedImage, onSelectImage, tab }: CanvasProps) {
  const model = cards.find((c) => c.kind === 'model3d' && c.id === tab)
  const others = cards.filter((c) => c.kind !== 'model3d')

  if (model) {
    return (
      <Suspense fallback={<div className="canvas-empty">Loading the 3D viewer…</div>}>
        <Model3DViewer key={model.id} data={model.data as unknown as Model3DData} />
      </Suspense>
    )
  }
  return (
    <div className="canvas-cards">
      {others.length === 0 ? (
        <div className="canvas-empty">Things Ultron shows you will appear here.</div>
      ) : (
        [...others].reverse().map((card) => (
          <section key={card.id} className="card">
            <header className="card-head">
              <span className="card-title">{card.title}</span>
              <span className="card-id">{card.id}</span>
              <button className="card-close" onClick={() => onClose(card.id)} aria-label="Close card">
                ×
              </button>
            </header>
            <CardBody card={card} selectedImage={selectedImage} onSelectImage={onSelectImage} />
          </section>
        ))
      )}
    </div>
  )
}
