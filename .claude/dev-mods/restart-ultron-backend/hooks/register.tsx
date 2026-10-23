import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

const PANE = 'restart-ultron-backend'
const FOLDER = 'ULTRON_cBrain'
const status = atom({ plugin: 'restart-ultron-backend', key: 'status' } as const, 'Idle.')

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

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    if (await inUltron($)) {
      await $.command.register({ name: 'restart-backend', description: 'Restart the Ultron backend' })
      void $.ui.open({ id: PANE, title: 'Ultron' })
    }
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    if (!(await inUltron($))) return <Text dimColor>Only works in {FOLDER}.</Text>
    const text = await read($, status)

    return (
      <Box flexDirection="column">
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
