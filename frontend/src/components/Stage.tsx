// The centre of the HUD: the reactor core (Ultron's state, and the voice orb), or the
// canvas: cards and 3D models, each in a tab.

import { lazy, Suspense, useState } from 'react'
import { toolLabel } from '../labels'
import type { ActiveTool, CanvasCard, ConnectionState, ImageSelection, TerminalTab } from '../ws'
import Canvas from './Canvas'
import VoiceOrb, { type VoiceState } from './VoiceOrb'

// xterm is only loaded when Ultron first opens a terminal.
const Terminal = lazy(() => import('./Terminal'))

const VOICE_STATES: VoiceState[] = ['idle', 'listening', 'thinking', 'speaking']

const VOICE_PILL: Record<VoiceState, string> = {
  idle: 'MIC PAUSED',
  listening: 'LISTENING…',
  thinking: 'PROCESSING…',
  speaking: 'SPEAKING…',
}

// Sample captions for the voice preview (voice isn't connected yet: Phase 5b/5c).
const SAMPLE: Record<VoiceState, { you?: string; ultron?: string }> = {
  idle: {},
  listening: { you: "What's on my calendar tomorrow" },
  thinking: { you: "What's on my calendar tomorrow?" },
  speaking: {
    you: "What's on my calendar tomorrow?",
    ultron: 'You have three things tomorrow. The first is a dentist appointment at nine.',
  },
}

interface StageProps {
  cards: CanvasCard[]
  tab: string
  onTab: (tab: string) => void
  onClose: (id: string) => void
  selectedImage: ImageSelection | null
  onSelectImage: (selection: ImageSelection | null) => void
  terminals: TerminalTab[]
  onCloseTerminal: (id: string) => void
  busy: boolean
  activeTool: ActiveTool | null
  connection: ConnectionState
  voiceOn: boolean
  onVoice: (on: boolean) => void
}

function Waveform({ state }: { state: VoiceState }) {
  return (
    <div className={`waveform wave-${state}`} aria-hidden="true">
      {Array.from({ length: 15 }, (_, i) => (
        <span key={i} style={{ animationDelay: `${((i * 7) % 11) * 0.07}s` }} />
      ))}
    </div>
  )
}

function Core({ busy, activeTool, connection, voiceOn, onVoice }: Pick<StageProps, 'busy' | 'activeTool' | 'connection' | 'voiceOn' | 'onVoice'>) {
  const [preview, setPreview] = useState<VoiceState>('listening')
  const state: VoiceState = voiceOn ? preview : busy ? 'thinking' : 'idle'
  const sample = voiceOn ? SAMPLE[preview] : {}

  let pill: string
  if (voiceOn) pill = VOICE_PILL[state]
  else if (connection !== 'open') pill = connection === 'closed' ? 'BACKEND OFFLINE' : 'CONNECTING…'
  else if (busy) pill = activeTool ? toolLabel(activeTool).toUpperCase() : 'PROCESSING…'
  else pill = 'AWAITING COMMAND…'

  const cycle = () => setPreview(VOICE_STATES[(VOICE_STATES.indexOf(preview) + 1) % VOICE_STATES.length])

  return (
    <div className="core">
      <VoiceOrb
        state={state}
        onClick={voiceOn ? cycle : () => onVoice(true)}
        label={voiceOn ? 'Voice preview: next state' : 'Talk to Ultron'}
      />
      <div className="core-bottom">
        <Waveform state={state} />
        <button
          type="button"
          className={`core-pill${voiceOn ? ' on' : ''}`}
          onClick={() => onVoice(!voiceOn)}
          title={voiceOn ? 'End voice mode (Esc)' : 'Talk to Ultron'}
        >
          <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
            <rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor" />
            <path d="M6 11a6 6 0 0 0 12 0M12 17v4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <span>{pill}</span>
        </button>
        {voiceOn && (
          <div className="core-captions" aria-live="polite">
            {sample.you && (
              <div className={`caption${preview === 'listening' ? ' interim' : ''}`}>
                <b>YOU</b> {sample.you}
              </div>
            )}
            {sample.ultron && (
              <div className="caption caption-ultron">
                <b>ULTRON</b> {sample.ultron}
              </div>
            )}
            <div className="core-preview">
              <span>UI PREVIEW · VOICE NOT CONNECTED YET</span>
              {VOICE_STATES.map((s) => (
                <button key={s} type="button" className={s === preview ? 'active' : undefined} onClick={() => setPreview(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Stage(props: StageProps) {
  const { cards, tab, onTab, onClose, selectedImage, onSelectImage, terminals, onCloseTerminal } = props
  const models = cards.filter((c) => c.kind === 'model3d')
  const others = cards.filter((c) => c.kind !== 'model3d')

  return (
    <section className="stage" aria-label="Core and canvas">
      {(cards.length > 0 || terminals.length > 0) && (
        <nav className="stage-tabs" role="tablist">
          <button role="tab" aria-selected={tab === 'core'} className={tab === 'core' ? 'active' : ''} onClick={() => onTab('core')}>
            CORE
          </button>
          {others.length > 0 && (
            <button role="tab" aria-selected={tab === 'cards'} className={tab === 'cards' ? 'active' : ''} onClick={() => onTab('cards')}>
              CANVAS <span className="count">{others.length}</span>
            </button>
          )}
          {models.map((m) => (
            <span key={m.id} className={`stage-tab-3d${tab === m.id ? ' active' : ''}`}>
              <button role="tab" aria-selected={tab === m.id} onClick={() => onTab(m.id)}>
                3D · {m.title}
              </button>
              <button className="tab-close" onClick={() => onClose(m.id)} aria-label={`Close ${m.title}`}>
                ×
              </button>
            </span>
          ))}
          {terminals.map((t) => (
            <span key={t.id} className={`stage-tab-3d${tab === t.id ? ' active' : ''}`}>
              <button role="tab" aria-selected={tab === t.id} onClick={() => onTab(t.id)}>
                TERMINAL {t.number}
              </button>
              <button className="tab-close" onClick={() => onCloseTerminal(t.id)} aria-label={`Close terminal ${t.number}`}>
                ×
              </button>
            </span>
          ))}
        </nav>
      )}
      <div className="stage-body">
        {tab === 'core' ? (
          <Core {...props} />
        ) : (
          !terminals.some((t) => t.id === tab) && (
            <Canvas cards={cards} onClose={onClose} selectedImage={selectedImage} onSelectImage={onSelectImage} tab={tab} />
          )
        )}
        {terminals.length > 0 && (
          <Suspense fallback={null}>
            {terminals.map((t) => (
              <Terminal key={t.id} visible={tab === t.id} claude={t.claude} number={t.number} />
            ))}
          </Suspense>
        )}
      </div>
    </section>
  )
}
