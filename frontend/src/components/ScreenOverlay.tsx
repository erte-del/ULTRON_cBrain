// What's inside the overlay window: Ultron's latest answer above, the box you type in below.
// Plain view, no idea what window it's in: today it's portalled into a Picture-in-Picture
// window (useScreenOverlay.ts); the Mac overlay can render the same thing.

import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import type { ChatMessage, ConnectionState } from '../ws'
import ConfirmCard from './ConfirmCard'
import Markdown from './Markdown'

interface ViewProps {
  messages: ChatMessage[]
  connection: ConnectionState
  busy: boolean
  sharing: boolean
  error: string
  onAsk: (text: string, withScreen: boolean) => Promise<boolean>
  onShare: () => void
  onConfirm: (id: string, approved: boolean) => void
  onClose: () => void
}

// The last thing you asked and everything Ultron did since (answers, cards waiting for you).
function latestExchange(messages: ChatMessage[]) {
  const lastUser = messages.map((m) => m.role).lastIndexOf('user')
  return { question: messages[lastUser], after: messages.slice(lastUser + 1) }
}

export function ScreenOverlayView({ messages, connection, busy, sharing, error, onAsk, onShare, onConfirm, onClose }: ViewProps) {
  const [draft, setDraft] = useState('')
  const [withScreen, setWithScreen] = useState(true)
  const [sending, setSending] = useState(false)
  const answerRef = useRef<HTMLDivElement>(null)
  const { question, after } = latestExchange(messages)

  useEffect(() => {
    const el = answerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, busy])

  const canSend = connection === 'open' && !busy && !sending && draft.trim() !== ''
  const submit = async () => {
    if (!canSend) return
    setSending(true)
    if (await onAsk(draft, withScreen && sharing)) setDraft('')
    setSending(false)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void submit()
    }
  }

  const shown = after.filter((m) => m.role !== 'user')
  return (
    <div className="so">
      <div className="so-answer" ref={answerRef}>
        {question && <div className="so-question">{question.text || 'Screen'}</div>}
        {shown.map((m) =>
          m.role === 'confirm' && m.confirm ? (
            <ConfirmCard key={m.id} confirm={m.confirm} onAnswer={(approved) => onConfirm(m.id, approved)} />
          ) : (
            <div key={m.id} className={`so-msg so-${m.role}${m.error ? ' so-error' : ''}`}>
              {m.text ? <Markdown text={m.text} /> : <span className="so-dim">…</span>}
            </div>
          ),
        )}
        {busy && shown.length === 0 && <div className="so-dim">Thinking…</div>}
        {!question && shown.length === 0 && (
          <div className="so-dim">
            {sharing ? "I'm watching your screen. Ask me about anything on it." : 'Share your screen so I can see it.'}
          </div>
        )}
        {error && <div className="so-msg so-error">{error}</div>}
      </div>

      <div className="so-bar">
        <span className={`so-eye${sharing ? ' on' : ''}`} title={sharing ? 'Ultron can see your screen' : 'Ultron cannot see your screen'}>
          {sharing ? '● Seeing your screen' : '○ Not seeing your screen'}
        </span>
        {sharing ? (
          <label className="so-toggle" title="Attach a picture of the screen to each message">
            <input type="checkbox" checked={withScreen} onChange={(e) => setWithScreen(e.target.checked)} /> send screen
          </label>
        ) : (
          <button type="button" className="so-btn" onClick={onShare}>Share my screen</button>
        )}
        <button type="button" className="so-btn" onClick={onClose} title="Close the overlay and stop looking at your screen">Close</button>
      </div>

      <textarea
        className="so-input"
        rows={2}
        value={draft}
        placeholder={sharing && withScreen ? 'Ask about your screen…' : 'Ask Ultron…'}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={connection !== 'open'}
        autoFocus
      />
    </div>
  )
}

interface PortalProps extends Omit<ViewProps, 'onShare'> {
  win: Window
  onShare: (from: Window) => void
}

/** The view inside a Picture-in-Picture window. */
export default function ScreenOverlay({ win, onShare, ...view }: PortalProps) {
  return createPortal(<ScreenOverlayView {...view} onShare={() => onShare(win)} />, win.document.body)
}
