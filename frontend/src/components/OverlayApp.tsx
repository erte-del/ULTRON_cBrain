// The page shown inside the Mac app's overlay window (http://127.0.0.1:8000/?overlay=1).
// Its own connection to Ultron; the view is the same one the browser overlay uses.

import { useCallback, useEffect, useState } from 'react'
import { NativeScreenSource } from '../screen/nativeScreenSource'
import { uploadScreen, useUltron } from '../ws'
import { ScreenOverlayView } from './ScreenOverlay'

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

export default function OverlayApp() {
  const ultron = useUltron()
  const [source] = useState(() => new NativeScreenSource())
  const [sharing, setSharing] = useState(false)
  const [error, setError] = useState('')

  const share = useCallback(async () => {
    setError('')
    try {
      await source.start()
      setSharing(true)
    } catch (e) {
      setSharing(false)
      setError(errorText(e))
    }
  }, [source])
  useEffect(() => {
    source.start().then(() => setSharing(true), (e) => setError(errorText(e)))
  }, [source])

  const ask = useCallback(async (text: string, withScreen: boolean) => {
    setError('')
    let files: Awaited<ReturnType<typeof uploadScreen>>[] = []
    if (withScreen && source.active) {
      try {
        files = [await uploadScreen(await source.grab())]
      } catch (e) {
        setError(`Couldn't capture the screen: ${errorText(e)}`)
        return false
      }
    }
    return ultron.sendText(text, files)
  }, [source, ultron])

  return (
    <ScreenOverlayView
      messages={ultron.messages}
      connection={ultron.connection}
      busy={ultron.busy}
      sharing={sharing}
      error={error}
      onAsk={ask}
      onShare={share}
      onConfirm={ultron.answerConfirm}
      onClose={() => source.hide()}
    />
  )
}
