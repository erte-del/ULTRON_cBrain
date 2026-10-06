// Right-hand HUD panels: usage (plan limit + tokens + model), system log, terminal.

import { useEffect, useRef } from 'react'
import { gatewayModelName, toolLabel } from '../labels'
import { useNow } from '../useNow'
import type { ActiveTool, BrainSettings, ConnectionState, LogLine, ModelAlias, UsageSnapshot, UsageWindow } from '../ws'
import Panel from './Panel'

const fmt = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n)

function countdown(resetsAt: number, now: Date): string {
  const mins = Math.max(0, Math.round((resetsAt * 1000 - now.getTime()) / 60000))
  const h = Math.floor(mins / 60)
  if (h >= 24) return `in ${Math.floor(h / 24)}d ${h % 24}h`
  return h > 0 ? `in ${h}h ${mins % 60}m` : `in ${mins}m`
}

function resetTime(resetsAt: number): string {
  const d = new Date(resetsAt * 1000)
  const sameDay = d.toDateString() === new Date().toDateString()
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  return sameDay ? time : `${d.toLocaleDateString([], { weekday: 'short' })} ${time}`
}

function Meter({ label, window, now }: { label: string; window?: UsageWindow; now: Date }) {
  if (!window) {
    return (
      <div className="meter">
        <div className="meter-label">{label}</div>
        <div className="meter-value dim">--</div>
        <div className="meter-bar" />
        <div className="meter-sub">after Ultron's next reply</div>
      </div>
    )
  }
  // Shown as "used", like Claude's own usage screen.
  const used = Math.min(1, Math.max(0, window.used))
  const tone = used > 0.95 ? ' danger' : used > 0.8 ? ' warn' : ''
  return (
    <div className={`meter${tone}`}>
      <div className="meter-label">{label}</div>
      <div className="meter-value">
        {Math.round(used * 100)}% <span>used</span>
      </div>
      <div className="meter-bar">
        <span style={{ width: `${used * 100}%` }} />
      </div>
      <div className="meter-sub">
        {window.resets_at ? `resets ${resetTime(window.resets_at)} · ${countdown(window.resets_at, now)}` : 'window just reset'}
      </div>
      {window.reported_at > 0 && (
        <div className="meter-sub" title="Includes Claude Code and claude.ai, but Ultron only gets the number with its replies.">
          as of {resetTime(window.reported_at)}
        </div>
      )}
    </div>
  )
}

const MODELS: { id: ModelAlias | null; label: string; hint: string }[] = [
  { id: null, label: 'AUTO', hint: 'Ultron picks (Sonnet by default)' },
  { id: 'haiku', label: 'HAIKU', hint: 'Fastest, cheapest' },
  { id: 'sonnet', label: 'SONNET', hint: 'The default' },
  { id: 'opus', label: 'OPUS', hint: 'Strongest, uses the most of your limit' },
]

interface UsagePanelProps {
  usage: UsageSnapshot | null
  settings: BrainSettings | null
  modelOverride: ModelAlias | null
  onModel: (model: ModelAlias | null) => void
  onGatewayModel: (model: string) => void
}

function GatewayModels({ settings, onGatewayModel }: { settings: BrainSettings; onGatewayModel: (model: string) => void }) {
  return (
    <div className="model-buttons">
      {settings.gateway_models.map((id) => {
        const { provider, model } = gatewayModelName(id)
        return (
          <button
            key={id}
            type="button"
            className={`model-btn model-gateway${settings.gateway_model === id ? ' active' : ''}`}
            onClick={() => onGatewayModel(id)}
            aria-pressed={settings.gateway_model === id}
            title={id}
          >
            <span className="model-dot" />
            {provider.toUpperCase()}
            <span className="model-sub">{model}</span>
          </button>
        )
      })}
    </div>
  )
}

export function UsagePanel({ usage, settings, modelOverride, onModel, onGatewayModel }: UsagePanelProps) {
  const now = useNow(30_000)
  const onClaude = settings?.provider !== 'omniroute'
  const t = usage?.tokens
  const total = t ? t.input + t.cache_write + t.cache_read + t.output : 0

  return (
    <Panel title="USAGE" tag={onClaude ? 'PRO PLAN' : 'OMNIROUTE'} className="usage-panel">
      {onClaude ? (
        <div className="meters">
          <Meter label="5-HOUR LIMIT" window={usage?.windows.five_hour} now={now} />
          <Meter label="WEEKLY · ALL MODELS" window={usage?.windows.seven_day} now={now} />
        </div>
      ) : (
        <div className="usage-note">OmniRoute doesn't use your Pro limit.</div>
      )}

      <div className="usage-section">
        <div className="usage-label">ULTRON · THIS 5-HOUR WINDOW</div>
        <div className="usage-total">
          {fmt(total)} <span>tokens</span>
        </div>
        <dl className="usage-rows" title="Cache reads cost about a tenth of new input">
          <div><dt>New input</dt><dd>{fmt(t?.input ?? 0)}</dd></div>
          <div><dt>Cache writes</dt><dd>{fmt(t?.cache_write ?? 0)}</dd></div>
          <div><dt>Cache reads</dt><dd>{fmt(t?.cache_read ?? 0)}</dd></div>
          <div><dt>Output</dt><dd>{fmt(t?.output ?? 0)}</dd></div>
          <div className="usage-conv"><dt>This conversation</dt><dd>{fmt(usage?.context_tokens ?? 0)}</dd></div>
        </dl>
      </div>

      <div className="usage-label">{onClaude ? 'MODEL' : 'MODEL · OMNIROUTE'}</div>
      {onClaude || !settings ? (
        <div className="model-buttons">
          {MODELS.map((m) => (
            <button
              key={m.label}
              type="button"
              className={`model-btn model-${m.id ?? 'auto'}${modelOverride === m.id ? ' active' : ''}`}
              onClick={() => onModel(m.id)}
              aria-pressed={modelOverride === m.id}
              title={m.hint}
            >
              <span className="model-dot" />
              {m.label}
            </button>
          ))}
        </div>
      ) : (
        <GatewayModels settings={settings} onGatewayModel={onGatewayModel} />
      )}
    </Panel>
  )
}

export function LogPanel({ log }: { log: LogLine[] }) {
  const listRef = useRef<HTMLOListElement>(null)
  useEffect(() => {
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [log])

  return (
    <Panel title="LOG" tag="RT-LOG" className="log-panel">
      <ol className="log" ref={listRef}>
        {log.length === 0 && <li className="log-empty">No activity yet.</li>}
        {log.map((l) => (
          <li key={l.id} className={l.tone ? `log-${l.tone}` : undefined}>
            <time>[{l.time}]</time> {l.text}
          </li>
        ))}
      </ol>
    </Panel>
  )
}

const COMMANDS: Record<string, string> = {
  WebSearch: 'search',
  WebFetch: 'fetch',
  ToolSearch: 'find-tool',
  ask_expert: 'consult-opus',
  show_on_canvas: 'display',
  search_3d_library: 'find-3d',
  show_from_3d_library: 'open-3d',
  show_3d_asset: 'fetch-3d',
  preview_3d: 'build-3d --preview',
  export_3d: 'build-3d --final',
}

interface TerminalPanelProps {
  busy: boolean
  activeTool: ActiveTool | null
  connection: ConnectionState
}

export function TerminalPanel({ busy, activeTool, connection }: TerminalPanelProps) {
  let command: string
  let status: string
  if (connection !== 'open') {
    command = 'ultron --reconnect'
    status = connection === 'closed' ? 'Backend offline. Waiting for it to come back…' : 'Connecting…'
  } else if (activeTool) {
    const cmd = COMMANDS[activeTool.name] ?? activeTool.name.replace(/_/g, '-').toLowerCase()
    command = `ultron --${cmd}${activeTool.detail ? ` "${activeTool.detail}"` : ''}`
    status = toolLabel(activeTool)
  } else if (busy) {
    command = 'ultron --process'
    status = 'Working on your request…'
  } else {
    command = 'ultron --await-input'
    status = 'Standing by.'
  }

  return (
    <Panel title="TERMINAL" tag="ROOT@ULTRON" className="terminal-panel">
      <div className="terminal">
        <div className="terminal-cmd">
          <span className="prompt">&gt;_</span> {command}
          {!busy && connection === 'open' && <span className="terminal-cursor" />}
        </div>
        <div className="terminal-status">{status}</div>
      </div>
    </Panel>
  )
}
