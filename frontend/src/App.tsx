import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import './App.css'
import Chat from './components/Chat'
import Panel from './components/Panel'
import ScreenOverlay from './components/ScreenOverlay'
import { LogPanel, TerminalPanel, UsagePanel } from './components/SidePanels'
import Stage, { Core } from './components/Stage'
import TopBar from './components/TopBar'
import { screenOverlaySupported, useScreenOverlay } from './screen/useScreenOverlay'
import { useSwipePanes } from './useSwipePanes'
import { morph } from './morph'
import { startMic } from './mic'
import { speaker } from './speaker'
import { useUltron } from './ws'

const PANES = [['chat', 'CHAT'], ['stage', 'CANVAS'], ['status', 'STATUS']] as const
const PANE_IDS = PANES.map(([id]) => id)

// In voice mode, "go back to typing", "switch to texting", "text mode"... ends voice mode.
const BACK_TO_TYPING = /\b(?:(?:back|switch|go|change)\s+(?:back\s+)?to\s+(?:typing|texting|text|keyboard)|(?:typing|texting|text)\s+mode)\b/i

// In voice mode, talking over Ultron stops its reply (the server does that). If all you
// said was "stop", "wait", "never mind"..., that's all: it isn't sent as a message.
const JUST_STOP = /^\W*(?:(?:ok(?:ay)?|ultron)\W+)?(?:stop|wait|hold on|never ?mind|shut up|enough|that'?s enough|quiet|be quiet|cancel)(?:\W+(?:it|that|please|ultron|stop|wait))*\W*$/i

// "look at my screen" on its own (not a question about screens) opens the screen overlay.
const LOOK_AT_SCREEN = /^\s*(?:ultron\W+)?(?:please\s+)?(?:(?:can|could) you\s+)?(?:look at|watch|see)\s+(?:my|the)\s+screen\W*$/i

// HUD layout: chat on the left, the core / canvas in the middle, status on the right.
// A phone shows one of the three at a time (App.css): drag sideways (useSwipePanes), or
// use the bar at the bottom.
export default function App() {
  const heard = useRef((_text: string) => {}) // what you said in voice mode: set below
  const ultron = useUltron(heard)
  const [pane, setPane] = useState<(typeof PANES)[number][0]>('chat')
  const [voiceOn, setVoiceOn] = useState(false)
  const [micError, setMicError] = useState('')
  const level = useRef(0) // how loud you are (0..1), for the orb
  // Each switch picks one of three animations at random (morph.ts): the fold (3) is 6
  // points likelier than each of the others, 37.3% against 31.3% each.
  const setVoice = useCallback((on: boolean) => {
    const r = Math.random() * 100
    morph(() => setVoiceOn(on), on ? 'voice' : 'text', r < 94 / 3 ? 1 : r < 188 / 3 ? 2 : 3)
  }, [])
  // In voice mode a canvas takes the whole left side and the core drifts under the usage
  // panel; the tab switch is animated, so the tab on screen trails the real one by a frame.
  const [shownTab, setShownTab] = useState(ultron.stageTab)
  useEffect(() => {
    if (ultron.stageTab === shownTab) return
    if (voiceOn) morph(() => setShownTab(ultron.stageTab), 'voice')
    else setShownTab(ultron.stageTab)
  }, [ultron.stageTab, shownTab, voiceOn])
  const tab = voiceOn ? shownTab : ultron.stageTab
  const { ref: gridRef, go, touch } = useSwipePanes(PANE_IDS, pane, setPane)
  const screen = useScreenOverlay(ultron.sendText)
  const canWatch = screenOverlaySupported()
  const send = useCallback((text: string, files: Parameters<typeof ultron.sendText>[1] = [], voice = false) => {
    if (voiceOn && BACK_TO_TYPING.test(text) && text.split(/\s+/).length <= 8) {
      setVoice(false)
      return true
    }
    if (canWatch && LOOK_AT_SCREEN.test(text) && !files?.length) {
      void screen.open() // this key press is the click the browser wants
      return true
    }
    return ultron.sendText(text, files, voice)
  }, [canWatch, screen, ultron, voiceOn, setVoice])
  heard.current = (text) => !JUST_STOP.test(text) && send(text, [], true)

  // Voice mode: the mic streams to the server, which hears when you've finished and sends
  // back the words (voice.transcript -> heard).
  const { voiceMode, sendAudio } = ultron
  useEffect(() => {
    if (!voiceOn) return
    let stop: (() => void) | undefined
    let ended = false
    setMicError('')
    speaker.unlock()
    voiceMode(true)
    startMic((pcm, loud) => {
      level.current = loud
      sendAudio(pcm)
    })
      .then((s) => (ended ? s() : (stop = s)))
      .catch((e: Error) => {
        if (ended) return
        setMicError(`Microphone: ${e.message}`)
        setVoice(false)
      })
    return () => {
      ended = true
      stop?.()
      speaker.stop()
      voiceMode(false)
      level.current = 0
    }
  }, [voiceOn, voiceMode, sendAudio, setVoice])
  const lastText = (role: 'user' | 'assistant') => ultron.messages.findLast((m) => m.role === role)?.text
  const speaking = useSyncExternalStore(speaker.subscribe, () => speaker.speaking)
  // The orb follows Ultron's voice while it speaks, yours otherwise.
  const orbLevel = useMemo(() => ({ get current() { return speaker.speaking ? speaker.level : level.current } }), [])
  const { stop: stopReply } = ultron
  const hush = useCallback(() => {
    speaker.stop()
    stopReply()
  }, [stopReply])
  const voice = {
    captions: { hearing: ultron.hearing, you: lastText('user'), ultron: lastText('assistant') },
    level: orbLevel,
    speaking,
    onStop: hush,
  }

  return (
    <div className="hud">
      <TopBar
        connection={ultron.connection}
        busy={ultron.busy}
        settings={ultron.settings}
        canStartNewChat={!ultron.busy && ultron.connection === 'open' && ultron.messages.length > 0}
        onNewChat={ultron.newChat}
        onProvider={ultron.setProvider}
        savedChats={ultron.savedChats}
        maxSavedChats={ultron.maxSavedChats}
        canSaveChat={!ultron.busy && ultron.connection === 'open' && ultron.messages.length > 0}
        canLoadChat={!ultron.busy && ultron.connection === 'open'}
        onSaveChat={ultron.saveChat}
        onLoadChat={ultron.loadChat}
        onDeleteChat={ultron.deleteChat}
        memories={ultron.memories}
        memoryCategories={ultron.memoryCategories}
        onSaveMemory={ultron.saveMemory}
        onDeleteMemory={ultron.deleteMemory}
        onWipeMemory={ultron.wipeMemory}
        jobs={ultron.jobs}
        jobRuns={ultron.jobRuns}
        onJob={ultron.updateJob}
        screenSupported={canWatch}
        screenOpen={!!screen.win}
        onScreen={() => (screen.win ? screen.close() : void screen.open())}
        onTyping={voiceOn ? () => setVoice(false) : undefined}
      />
      {micError && (
        <div className="screen-toast" role="alert" onClick={() => setMicError('')}>{micError}</div>
      )}
      {screen.error && !screen.win && (
        <div className="screen-toast" role="alert" onClick={() => screen.open()}>{screen.error}</div>
      )}
      {screen.win && (
        <ScreenOverlay
          win={screen.win}
          messages={ultron.messages}
          connection={ultron.connection}
          busy={ultron.busy}
          sharing={screen.sharing}
          error={screen.error}
          onAsk={screen.ask}
          onShare={screen.share}
          onConfirm={ultron.answerConfirm}
          onClose={screen.close}
        />
      )}

      <main className={`hud-grid pane-${pane}${voiceOn ? ' voice' : ''}`} ref={gridRef} {...touch}>
        <Panel title="COMMS" tag="RT-LINK" className="comms-panel">
          <Chat
            messages={ultron.messages}
            connection={ultron.connection}
            busy={ultron.busy}
            activeTool={ultron.activeTool}
            retry={ultron.retry}
            onSend={send}
            onStop={ultron.stop}
            onConfirm={ultron.answerConfirm}
            voiceOn={voiceOn}
            onVoice={setVoice}
          />
        </Panel>

        <Stage
          cards={ultron.cards}
          tab={tab}
          onTab={ultron.setStageTab}
          onClose={ultron.closeCard}
          selectedImage={ultron.selectedImage}
          onSelectImage={ultron.selectImage}
          terminals={ultron.terminals}
          onCloseTerminal={ultron.closeTerminal}
          busy={ultron.busy}
          activeTool={ultron.activeTool}
          connection={ultron.connection}
          voiceOn={voiceOn}
          onVoice={setVoice}
          {...voice}
        />

        <div className="hud-right">
          <UsagePanel
            usage={ultron.usage}
            settings={ultron.settings}
            modelOverride={ultron.modelOverride}
            onModel={ultron.setModelOverride}
            onGatewayModel={ultron.setGatewayModel}
          />
          <LogPanel log={ultron.log} />
          <TerminalPanel busy={ultron.busy} activeTool={ultron.activeTool} connection={ultron.connection} />
          {voiceOn && tab !== 'core' && (
            <div className="voice-core">
              <Core busy={ultron.busy} activeTool={ultron.activeTool} connection={ultron.connection} voiceOn onVoice={setVoice} {...voice} />
            </div>
          )}
        </div>
      </main>

      <nav className="hud-panes" aria-label="Sections">
        {PANES.map(([id, label]) => (
          <button key={id} type="button" className={pane === id ? 'active' : ''} aria-pressed={pane === id} onClick={() => go(id)}>
            {label}
            {id === 'stage' && ultron.cards.length > 0 && <span className="count">{ultron.cards.length}</span>}
          </button>
        ))}
      </nav>
    </div>
  )
}
