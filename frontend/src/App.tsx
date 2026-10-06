import { useCallback, useEffect, useState } from 'react'
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
import { useUltron } from './ws'

const PANES = [['chat', 'CHAT'], ['stage', 'CANVAS'], ['status', 'STATUS']] as const
const PANE_IDS = PANES.map(([id]) => id)

// In voice mode, "go back to typing", "switch to texting", "text mode"... ends voice mode.
const BACK_TO_TYPING = /\b(?:(?:back|switch|go|change)\s+(?:back\s+)?to\s+(?:typing|texting|text|keyboard)|(?:typing|texting|text)\s+mode)\b/i

// "look at my screen" on its own (not a question about screens) opens the screen overlay.
const LOOK_AT_SCREEN = /^\s*(?:ultron\W+)?(?:please\s+)?(?:(?:can|could) you\s+)?(?:look at|watch|see)\s+(?:my|the)\s+screen\W*$/i

// HUD layout: chat on the left, the core / canvas in the middle, status on the right.
// A phone shows one of the three at a time (App.css): drag sideways (useSwipePanes), or
// use the bar at the bottom.
export default function App() {
  const ultron = useUltron()
  const [pane, setPane] = useState<(typeof PANES)[number][0]>('chat')
  const [voiceOn, setVoiceOn] = useState(false) // UI only for now (Phase 5a)
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
  const send = useCallback((text: string, files: Parameters<typeof ultron.sendText>[1]) => {
    if (voiceOn && BACK_TO_TYPING.test(text) && text.split(/\s+/).length <= 8) {
      setVoice(false)
      return true
    }
    if (canWatch && LOOK_AT_SCREEN.test(text) && !files?.length) {
      void screen.open() // this key press is the click the browser wants
      return true
    }
    return ultron.sendText(text, files)
  }, [canWatch, screen, ultron, voiceOn, setVoice])

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
              <Core busy={ultron.busy} activeTool={ultron.activeTool} connection={ultron.connection} voiceOn onVoice={setVoice} />
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
