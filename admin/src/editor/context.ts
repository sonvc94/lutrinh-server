import { createContext, useContext, useSyncExternalStore } from 'react'
import type { RouteOut } from '../api/types'
import type { DraftSaver, SaverState } from '../draft/saver'

export interface EditorContext {
  routeId: string
  route: RouteOut | undefined
  saver: DraftSaver
}

export const EditorCtx = createContext<EditorContext | null>(null)

export function useEditor(): EditorContext & { state: SaverState } {
  const ctx = useContext(EditorCtx)
  if (!ctx) throw new Error('useEditor outside RouteEditor')
  const state = useSyncExternalStore(ctx.saver.subscribe, () => ctx.saver.snapshot)
  return { ...ctx, state }
}
