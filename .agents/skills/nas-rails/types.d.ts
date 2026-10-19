export type RailsNotes = { stack: string; log: boolean; index: boolean }

export type Rails = {
  notes: RailsNotes[]
  /** Stacks whose files changed in HEAD since refs/deploy/<stack>; null = record unreadable. */
  undeployed: [string, boolean | null][]
  /** Stacks with no deploy record yet. */
  unrecorded: number
  drift: { src: string; dst: string }[]
}

declare module 'claude-code' {
  interface PluginState {
    'nas-rails': { rails: Rails | null; closing: boolean; isHidden: boolean; loadedNotes: string[] }
  }
}
