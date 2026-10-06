// HUD top bar: name, system status, local time, brain, New chat, saved chats, memory, schedule and settings.

import { useEffect, useRef, useState } from 'react'
import { gatewayModelName } from '../labels'
import { useNow } from '../useNow'
import type { BrainSettings, ConnectionState, Job, JobAction, JobRun, Memory, Provider, SavedChat } from '../ws'

interface TopBarProps {
  connection: ConnectionState
  busy: boolean
  settings: BrainSettings | null
  canStartNewChat: boolean
  onNewChat: () => void
  onProvider: (provider: Provider) => void
  savedChats: SavedChat[]
  maxSavedChats: number
  canSaveChat: boolean
  canLoadChat: boolean
  onSaveChat: () => void
  onLoadChat: (id: string) => void
  onDeleteChat: (id: string) => void
  memories: Memory[]
  memoryCategories: string[]
  onSaveMemory: (text: string, category: string, id?: string) => void
  onDeleteMemory: (id: string) => void
  onWipeMemory: () => void
  jobs: Job[]
  jobRuns: JobRun[]
  onJob: (id: string, action: JobAction) => void
  screenSupported: boolean
  screenOpen: boolean
  onScreen: () => void
  onTyping?: () => void // set in voice mode: back to typing
}

/** A menu under a top-bar button that closes on a click outside or Esc. */
function usePopup() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => ref.current?.contains(e.target as Node) || setOpen(false)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('mousedown', onClick)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onClick)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])
  return { open, setOpen, ref }
}

function SavedChats(props: Pick<TopBarProps, 'savedChats' | 'maxSavedChats' | 'canSaveChat' | 'canLoadChat' | 'onSaveChat' | 'onLoadChat' | 'onDeleteChat'>) {
  const { open, setOpen, ref } = usePopup()
  const { savedChats, maxSavedChats } = props

  return (
    <div className="settings" ref={ref}>
      <button
        type="button"
        className={`icon-btn${open ? ' active' : ''}`}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label="Saved chats"
        title="Saved chats"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path d="M5 3h11l3 3v15H5z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
          <path d="M8 3v5h7V3M8 21v-7h8v7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="settings-menu" role="dialog" aria-label="Saved chats">
          <div className="settings-head">
            SAVED CHATS · {savedChats.length}/{maxSavedChats}
          </div>
          <button
            type="button"
            className="provider"
            onClick={() => {
              props.onSaveChat()
              setOpen(false)
            }}
            disabled={!props.canSaveChat}
          >
            <span className="provider-name">Save this chat</span>
            <span className="provider-note">
              Saving it again later updates the same slot.
            </span>
          </button>
          {savedChats.map((chat) => (
            <div key={chat.id} className="saved-chat">
              <button
                type="button"
                className="provider"
                disabled={!props.canLoadChat}
                onClick={() => {
                  props.onLoadChat(chat.id)
                  setOpen(false)
                }}
              >
                <span className="provider-name">{chat.title}</span>
                <span className="provider-note">
                  {new Date(chat.saved_at * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                  {chat.provider === 'omniroute' && ' · OmniRoute'}
                </span>
              </button>
              <button
                type="button"
                className="icon-btn"
                onClick={() => props.onDeleteChat(chat.id)}
                aria-label={`Delete "${chat.title}"`}
                title="Delete"
              >
                ×
              </button>
            </div>
          ))}
          <div className="settings-foot">Loading a chat replaces the current conversation.</div>
        </div>
      )}
    </div>
  )
}

type MemoryProps = Pick<TopBarProps, 'memories' | 'memoryCategories' | 'onSaveMemory' | 'onDeleteMemory' | 'onWipeMemory'>

/** What Ultron remembers about you: search, add, edit, delete, export, wipe. */
function MemoryMenu({ memories, memoryCategories, onSaveMemory, onDeleteMemory, onWipeMemory }: MemoryProps) {
  const { open, setOpen, ref } = usePopup()
  const [search, setSearch] = useState('')
  // The memory being edited; id undefined = a new one.
  const [draft, setDraft] = useState<{ id?: string; text: string; category: string } | null>(null)

  const words = search.toLowerCase().split(/\s+/).filter(Boolean)
  const shown = memories.filter((m) => words.every((w) => `${m.category} ${m.text}`.toLowerCase().includes(w)))

  const save = () => {
    if (!draft?.text.trim()) return
    onSaveMemory(draft.text, draft.category, draft.id)
    setDraft(null)
  }

  const exportAll = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(memories, null, 1)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'ultron-memory.json'
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="settings" ref={ref}>
      <button
        type="button"
        className={`icon-btn${open ? ' active' : ''}`}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label="Memory"
        title="Memory: what Ultron remembers about you"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <rect x="6" y="6" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div className="settings-menu memory-menu" role="dialog" aria-label="Memory">
          <div className="settings-head">MEMORY · {memories.length}</div>
          {draft ? (
            <form
              className="memory-form"
              onSubmit={(e) => {
                e.preventDefault()
                save()
              }}
            >
              <select
                value={draft.category}
                onChange={(e) => setDraft({ ...draft, category: e.target.value })}
                aria-label="Category"
              >
                {memoryCategories.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <textarea
                value={draft.text}
                onChange={(e) => setDraft({ ...draft, text: e.target.value })}
                maxLength={500}
                rows={3}
                autoFocus
                placeholder="One short fact, e.g. Prefers meetings in the morning."
                aria-label="Memory"
              />
              <div className="memory-actions">
                <button type="submit" className="memory-btn" disabled={!draft.text.trim()}>
                  Save
                </button>
                <button type="button" className="memory-btn" onClick={() => setDraft(null)}>
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <>
              <input
                className="memory-search"
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search…"
                aria-label="Search memory"
              />
              <ul className="memory-list">
                {shown.length === 0 && (
                  <li className="memory-empty">
                    {memories.length ? 'Nothing matches.' : 'Nothing yet. Tell Ultron "remember that…", or add one here.'}
                  </li>
                )}
                {shown.map((m) => (
                  <li key={m.id} className="saved-chat">
                    <button
                      type="button"
                      className="provider"
                      onClick={() => setDraft({ id: m.id, text: m.text, category: m.category })}
                      title="Edit"
                    >
                      <span className="provider-name">{m.category}</span>
                      <span className="provider-note">{m.text}</span>
                    </button>
                    <button
                      type="button"
                      className="icon-btn"
                      onClick={() => onDeleteMemory(m.id)}
                      aria-label={`Delete "${m.text}"`}
                      title="Delete"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
              <div className="memory-actions">
                <button
                  type="button"
                  className="memory-btn"
                  onClick={() => setDraft({ text: '', category: memoryCategories[0] ?? 'facts' })}
                >
                  Add
                </button>
                <button type="button" className="memory-btn" onClick={exportAll} disabled={!memories.length}>
                  Export
                </button>
                <button
                  type="button"
                  className="memory-btn danger"
                  disabled={!memories.length}
                  onClick={() => window.confirm(`Delete all ${memories.length} memories? This can't be undone.`) && onWipeMemory()}
                >
                  Wipe all
                </button>
              </div>
            </>
          )}
          <div className="settings-foot">Ultron reads these when a new chat starts. Secrets are never stored.</div>
        </div>
      )}
    </div>
  )
}

const jobWhen = (job: Job) =>
  job.every_min
    ? `every ${job.every_min} min${job.once ? ', until it finds something' : ''}`
    : `${job.at} ${job.days.join(', ') || 'every day'}`

const RUN_STATUS: Record<JobRun['status'], string> = {
  told: '',
  nothing: 'Nothing to report.',
  skipped: 'Skipped: ',
  failed: 'Failed: ',
}

/** What Ultron does on its own: the jobs, and what their recent runs told you. */
function ScheduleMenu({ jobs, jobRuns, onJob }: Pick<TopBarProps, 'jobs' | 'jobRuns' | 'onJob'>) {
  const { open, setOpen, ref } = usePopup()
  const stamp = (t: number) => new Date(t * 1000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false })

  return (
    <div className="settings" ref={ref}>
      <button
        type="button"
        className={`icon-btn${open ? ' active' : ''}`}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label="Schedule"
        title="Schedule: what Ultron does on its own"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path d="M12 7v5l3.5 2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div className="settings-menu memory-menu schedule-menu" role="dialog" aria-label="Schedule">
          <div className="settings-head">SCHEDULED · {jobs.length}</div>
          <ul className="memory-list">
            {jobs.length === 0 && (
              <li className="memory-empty">
                Nothing scheduled. Ask Ultron, e.g. "give me a briefing every weekday at 8" or "tell me when Sarah replies".
              </li>
            )}
            {jobs.map((job) => (
              <li key={job.id} className={`job${job.enabled ? '' : ' paused'}`} title={job.prompt}>
                <div className="job-text">
                  <span className="provider-name">{job.title}</span>
                  <span className="provider-note">
                    {jobWhen(job)}
                    {!job.enabled && ' · paused'}
                  </span>
                </div>
                <button type="button" className="memory-btn" onClick={() => onJob(job.id, 'run')} title="Run it now">
                  Run
                </button>
                <button type="button" className="memory-btn" onClick={() => onJob(job.id, job.enabled ? 'pause' : 'resume')}>
                  {job.enabled ? 'Pause' : 'Resume'}
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  onClick={() => onJob(job.id, 'delete')}
                  aria-label={`Delete "${job.title}"`}
                  title="Delete"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
          <div className="settings-head">RECENT RUNS</div>
          <ul className="memory-list">
            {jobRuns.length === 0 && <li className="memory-empty">Nothing has run yet.</li>}
            {jobRuns.map((run) => (
              <li key={`${run.job_id}-${run.time}`} className={`run run-${run.status}`}>
                <span className="provider-name">
                  {run.title} · {stamp(run.time)}
                </span>
                <span className="provider-note">
                  {RUN_STATUS[run.status]}
                  {run.text}
                </span>
              </li>
            ))}
          </ul>
          <div className="settings-foot">
            Jobs only look things up; they can't send or change anything. Results also go to this Mac's notifications and your phone.
          </div>
        </div>
      )}
    </div>
  )
}

function Settings({ settings, onProvider }: Pick<TopBarProps, 'settings' | 'onProvider'>) {
  const { open, setOpen, ref } = usePopup()

  const choose = (provider: Provider) => {
    if (provider !== settings?.provider) onProvider(provider)
    setOpen(false)
  }

  return (
    <div className="settings" ref={ref}>
      <button
        type="button"
        className={`icon-btn${open ? ' active' : ''}`}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label="Settings"
        title="Settings"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="M12 2.5v3M12 18.5v3M21.5 12h-3M5.5 12h-3M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1M18.7 18.7l-2.1-2.1M7.4 7.4 5.3 5.3"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      </button>
      {open && (
        <div className="settings-menu" role="dialog" aria-label="Brain">
          <div className="settings-head">BRAIN</div>
          <button
            type="button"
            className={`provider${settings?.provider !== 'omniroute' ? ' active' : ''}`}
            onClick={() => choose('claude')}
          >
            <span className="provider-name">Claude · Pro login</span>
            <span className="provider-note">
              Sonnet by default, Haiku or Opus when useful. Uses your Pro limit. Gmail and your other connectors are on.
            </span>
          </button>
          <button
            type="button"
            className={`provider${settings?.provider === 'omniroute' ? ' active' : ''}`}
            onClick={() => choose('omniroute')}
          >
            <span className="provider-name">OmniRoute</span>
            <span className="provider-note">
              Your OmniRoute models ({settings?.gateway_models.map((m) => gatewayModelName(m).provider).join(', ')}) through{' '}
              {settings?.gateway_url ?? 'OmniRoute'}. Switch between them with the model buttons.
              Doesn't use your Pro limit. Connectors and web search are off, and tools may work less reliably.
            </span>
          </button>
          <div className="settings-foot">Switching starts a new conversation.</div>
        </div>
      )}
    </div>
  )
}

export default function TopBar({
  connection, busy, settings, canStartNewChat, onNewChat, onProvider,
  memories, memoryCategories, onSaveMemory, onDeleteMemory, onWipeMemory, jobs, jobRuns, onJob, screenSupported, screenOpen, onScreen, onTyping, ...chats
}: TopBarProps) {
  const now = useNow()
  const status =
    connection === 'open' ? (busy ? 'PROCESSING' : 'ONLINE') : connection === 'connecting' ? 'CONNECTING' : 'OFFLINE'

  return (
    <header className={`hud-top conn-${connection}`}>
      <div className="hud-brand">
        <span className="hud-logo" aria-hidden="true" />
        <div>
          <div className="hud-name">ULTRON</div>
          <div className="hud-motto">I was designed to save the world...</div>
        </div>
      </div>

      <div className="hud-readouts">
        <div>
          <div className="readout-key">SYSTEM STATUS</div>
          <div className={`readout-val status-${connection}`}>
            <span className="status-dot" />
            {status}
          </div>
        </div>
        <div>
          <div className="readout-key">LOCAL TIME</div>
          <div className="readout-val">{now.toLocaleTimeString([], { hour12: false })}</div>
        </div>
        <div>
          <div className="readout-key">BRAIN</div>
          <div className="readout-val">
            {settings?.provider === 'omniroute'
              ? `OMNIROUTE · ${gatewayModelName(settings.gateway_model).provider.toUpperCase()}`
              : 'CLAUDE · PRO'}
          </div>
        </div>
      </div>

      <div className="hud-actions">
        <button
          type="button"
          className="icon-btn"
          onClick={onNewChat}
          disabled={!canStartNewChat}
          aria-label="New chat"
          title="New chat. Long conversations use more of your limit with every message."
        >
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path d="M4 5h11M4 5v14h14V9" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            <path d="M18 2v6M15 5h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </button>
        {screenSupported && (
          <button
            type="button"
            className={`icon-btn${screenOpen ? ' active' : ''}`}
            onClick={onScreen}
            aria-label={screenOpen ? 'Stop watching my screen' : 'Look at my screen'}
            title={screenOpen
              ? 'Stop watching my screen and close the overlay'
              : 'Look at my screen: opens a small window that stays on top, where you can ask about what you see'}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
              <circle cx="12" cy="12" r="3" fill={screenOpen ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.8" />
            </svg>
          </button>
        )}
        <SavedChats {...chats} />
        <MemoryMenu
          memories={memories}
          memoryCategories={memoryCategories}
          onSaveMemory={onSaveMemory}
          onDeleteMemory={onDeleteMemory}
          onWipeMemory={onWipeMemory}
        />
        <ScheduleMenu jobs={jobs} jobRuns={jobRuns} onJob={onJob} />
        <Settings settings={settings} onProvider={onProvider} />
        {onTyping && (
          <button type="button" className="typing-btn" onClick={onTyping} title="Back to typing (Esc)">
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <rect x="2" y="6" width="20" height="12" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
              <path d="M6 10h1M10 10h1M14 10h1M17 10h1M7 14h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
            TYPE
          </button>
        )}
      </div>
    </header>
  )
}
