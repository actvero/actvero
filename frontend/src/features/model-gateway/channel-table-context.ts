import { createContext, useContext } from 'react'
import type { Channel } from './api'

export type ChannelActions = {
  pendingId: number | null
  testingId: number | null
  onEdit: (channel: Channel) => void
  onTest: (channel: Channel) => void
  onQuickTest: (channel: Channel) => void
  onStatus: (channel: Channel) => void
  onModels: (channel: Channel) => void
  onDelete: (channel: Channel) => void
}
export const ChannelTableContext = createContext<{
  actions: ChannelActions
  quotaPerUnit?: number | null
} | null>(null)

export function useChannelTable() {
  const value = useContext(ChannelTableContext)
  if (!value) throw new Error('Channel cells require the channel table context')
  return value
}
