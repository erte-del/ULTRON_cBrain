// The terminal tab: a real shell on this Mac, or over SSH on another device (backend/terminal.py), for you to type in.
// It stays mounted while you switch tabs, so whatever runs in it (Claude Code) keeps going;
// closing the tab or reloading the page ends the shell.

import { FitAddon } from '@xterm/addon-fit'
import { Terminal as XTerm } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { useEffect, useRef } from 'react'
import { API_BASE } from '../ws'

interface TerminalProps {
  visible: boolean
  claude: boolean // type `claude` once the shell is up
  number: number // the tab's number, so Ultron can ask for this terminal's screen
  device: string // another device (backend/devices.json) to SSH into; '' = a shell on this Mac
}

// Lines of scrollback (beyond the screen) sent with each snapshot for Ultron to read.
const SCROLLBACK = 200

// What the terminal shows as plain text: the screen plus some scrollback.
function snapshot(t: XTerm): string {
  const buf = t.buffer.active
  const lines: string[] = []
  for (let i = Math.max(0, buf.length - t.rows - SCROLLBACK); i < buf.length; i++) {
    lines.push(buf.getLine(i)?.translateToString(true) ?? '')
  }
  return lines.join('\n').trimEnd()
}

export default function Terminal({ visible, claude, number, device }: TerminalProps) {
  const box = useRef<HTMLDivElement>(null)
  const term = useRef<XTerm | null>(null)
  const startClaude = useRef(claude) // only matters when the shell starts

  useEffect(() => {
    // The HUD colours from index.css (xterm needs real colours, not CSS variables).
    const t = new XTerm({
      cursorBlink: true,
      fontFamily: "'JetBrains Mono', 'SF Mono', ui-monospace, Menlo, monospace",
      fontSize: 13,
      macOptionIsMeta: true,
      theme: { background: '#02080c', foreground: '#cdeef7', cursor: '#22d3ee', selectionBackground: '#13506a' },
    })
    const fit = new FitAddon()
    t.loadAddon(fit)
    t.open(box.current!)
    term.current = t

    const ws = new WebSocket(API_BASE.replace(/^http/, 'ws') + `/ws/terminal?n=${number}` +
        (device ? `&device=${encodeURIComponent(device)}${claude ? '&claude=1' : ''}` : ''))
    ws.binaryType = 'arraybuffer'
    const send = (msg: object) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify(msg))
    const resize = () => {
      if (!box.current?.clientWidth) return // hidden behind another tab
      fit.fit()
      send({ type: 'resize', cols: t.cols, rows: t.rows })
    }
    ws.onopen = () => {
      resize()
      // A device tab starts Claude on the server (over ssh); a plain tab types it here.
      if (startClaude.current && !device) send({ type: 'input', data: 'claude\r' })
    }
    // After output settles, send what's on screen so Ultron can read it (read_terminal).
    let snap: ReturnType<typeof setTimeout> | undefined
    const sendScreen = () => {
      clearTimeout(snap)
      snap = setTimeout(() => send({ type: 'screen', text: snapshot(t) }), 300)
    }
    ws.onmessage = (e) => t.write(new Uint8Array(e.data as ArrayBuffer), sendScreen)
    ws.onclose = (e) =>
      t.write(e.code === 1008 ? '\r\n[The terminal only works on the Mac itself.]\r\n' : `\r\n[${device ? `Connection to ${device} closed` : 'Shell closed'}]\r\n`)
    const typing = t.onData((data) => send({ type: 'input', data }))
    const observer = new ResizeObserver(resize) // also fires when the tab is shown again
    observer.observe(box.current!)

    return () => {
      clearTimeout(snap)
      observer.disconnect()
      typing.dispose()
      ws.close()
      t.dispose()
    }
  }, [])

  useEffect(() => {
    if (visible) term.current?.focus()
  }, [visible])

  return <div className="term-tab" ref={box} hidden={!visible} />
}
