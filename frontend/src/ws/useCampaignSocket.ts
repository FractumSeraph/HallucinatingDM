import { useEffect, useRef } from 'react'
import { acquireSocket, releaseSocket, CampaignSocket } from './connection'
import type { WsEvent } from '../types/events'

/** Shared campaign socket; handler receives every event for the campaign. */
export function useCampaignSocket(
  campaignId: string | undefined,
  onEvent?: (e: WsEvent) => void,
  onReconnect?: () => void,
): CampaignSocket | null {
  const socketRef = useRef<CampaignSocket | null>(null)
  const handlerRef = useRef(onEvent)
  const reconnectRef = useRef(onReconnect)
  handlerRef.current = onEvent
  reconnectRef.current = onReconnect

  useEffect(() => {
    if (!campaignId) return
    const socket = acquireSocket(campaignId)
    socketRef.current = socket
    const offEvent = socket.onEvent((e) => handlerRef.current?.(e))
    const offReconnect = socket.onReconnect(() => reconnectRef.current?.())
    return () => {
      offEvent()
      offReconnect()
      socketRef.current = null
      releaseSocket(campaignId)
    }
  }, [campaignId])

  return socketRef.current
}
