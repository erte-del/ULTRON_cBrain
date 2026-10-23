export type RestartStatus = string

declare module 'claude-code' {
  interface PluginState {
    'restart-ultron-backend': { status: RestartStatus; online: boolean | null }
  }
}
