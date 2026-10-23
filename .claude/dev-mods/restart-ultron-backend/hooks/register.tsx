import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

const PANE = 'restart-ultron-backend'
const FOLDER = 'ULTRON_cBrain'
const status = atom({ plugin: 'restart-ultron-backend', key: 'status' } as const, 'Idle.')
// null until the first check answers.
const online = atom({ plugin: 'restart-ultron-backend', key: 'online' } as const, null as boolean | null)

const HEALTH_URL = 'http://127.0.0.1:8000/health'
const POLL_MS = 3000
const TIMEOUT_MS = 1000

// Reload through launchd when autostart is on; else stop and start via the project's own scripts.
const RESTART = `
ROOT="$PWD"
AGENT="gui/$(id -u)/com.ultron.backend"
if launchctl print "$AGENT" >/dev/null 2>&1; then
  launchctl kickstart -k "$AGENT" || exit 1
else
  "$ROOT/scripts/stop_ultron.sh"
  sleep 1
  "$ROOT/scripts/start_ultron.sh" --no-open || exit 1
fi
for _ in $(seq 1 60); do curl -s -m 1 http://127.0.0.1:8000/health >/dev/null 2>&1 && exit 0; sleep 0.5; done
echo "backend did not come back on :8000" >&2; exit 1
`

const inUltron = async ($: { session: { root: () => Promise<string> } }) =>
  (await $.session.root()).split('/').pop() === FOLDER

// Any HTTP answer is online; a refused connection, or no answer within a second, is offline.
const ping = async ($: { http: { fetch: (url: string) => Promise<unknown> }; clock: { sleep: (ms: number) => Promise<void> } }) => {
  try {
    await Promise.race([
      $.http.fetch(HEALTH_URL),
      $.clock.sleep(TIMEOUT_MS).then(() => {
        throw new Error('timeout')
      }),
    ])
    return true
  } catch {
    return false
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    if (await inUltron($)) {
      await $.command.register({ name: 'restart-backend', description: 'Restart the Ultron backend' })
      void $.ui.open({ id: PANE, title: 'Ultron' })
      let busy = false
      const poll = async () => {
        if (busy) return
        busy = true
        try {
          const up = await ping($)
          await update($, online, prev => (prev === up ? prev : up)) // unchanged value: no redraw
        } finally {
          busy = false
        }
      }
      void poll()
      $.clock.every(POLL_MS, () => void poll())
    }
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    if (!(await inUltron($))) return <Text dimColor>Only works in {FOLDER}.</Text>
    const text = await read($, status)
    const up = await read($, online)

    return (
      <Box flexDirection="column">
        <Box>
          <Text color={up === null ? undefined : up ? '#3ddc84' : '#ff4d4d'} dimColor={up === null}>
            ●
          </Text>
          <Text dimColor={up === null}>{up === null ? ' Checking...' : up ? ' Backend online' : ' Backend offline'}</Text>
        </Box>
        <Button
          key="restart"
          label="Restart backend"
          onPress={async () => {
            if (!(await inUltron($))) return
            await update($, status, () => 'Restarting...')
            const r = await $.process.run(['bash', '-c', RESTART], {
              cwd: await $.session.root(),
              timeoutMs: 90000,
            })
            await update($, status, () =>
              r.exitCode === 0 ? 'Backend restarted.' : `Failed: ${r.stderr.trim().slice(-200) || r.exitCode}`,
            )
          }}
        />
        <Text dimColor>{text}</Text>
      </Box>
    )
  })
}
