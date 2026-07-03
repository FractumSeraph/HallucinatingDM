import type { WsEvent } from '../types/events'

type Listener = (event: WsEvent) => void

/**
 * One WebSocket per campaign with auto-reconnect and scene-channel
 * subscriptions. Events are an optimization: on (re)connect consumers refetch
 * via REST, so a dropped event can never corrupt state.
 */
export class CampaignSocket {
  private ws: WebSocket | null = null
  private listeners = new Set<Listener>()
  private scenes = new Set<string>()
  private retry = 0
  private closed = false
  private reconnectListeners = new Set<() => void>()

  constructor(private campaignId: string) {
    this.connect()
  }

  private connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    this.ws = new WebSocket(`${proto}://${location.host}/ws/campaigns/${this.campaignId}`)
    this.ws.onopen = () => {
      const isReconnect = this.retry > 0
      this.retry = 0
      for (const sceneId of this.scenes) {
        this.ws?.send(JSON.stringify({ type: 'scene.subscribe', scene_id: sceneId }))
      }
      if (isReconnect) this.reconnectListeners.forEach((fn) => fn())
    }
    this.ws.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as WsEvent
        this.listeners.forEach((fn) => fn(event))
      } catch {
        /* ignore malformed frames */
      }
    }
    this.ws.onclose = () => {
      this.ws = null
      if (this.closed) return
      const delay = Math.min(500 * 2 ** this.retry, 10_000)
      this.retry += 1
      setTimeout(() => !this.closed && this.connect(), delay)
    }
  }

  subscribeScene(sceneId: string) {
    this.scenes.add(sceneId)
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'scene.subscribe', scene_id: sceneId }))
    }
  }

  unsubscribeScene(sceneId: string) {
    this.scenes.delete(sceneId)
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'scene.unsubscribe', scene_id: sceneId }))
    }
  }

  onEvent(fn: Listener): () => void {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  onReconnect(fn: () => void): () => void {
    this.reconnectListeners.add(fn)
    return () => this.reconnectListeners.delete(fn)
  }

  close() {
    this.closed = true
    this.ws?.close()
  }
}

const sockets = new Map<string, { socket: CampaignSocket; refs: number }>()

/** Ref-counted socket per campaign so multiple components can share one. */
export function acquireSocket(campaignId: string): CampaignSocket {
  let entry = sockets.get(campaignId)
  if (!entry) {
    entry = { socket: new CampaignSocket(campaignId), refs: 0 }
    sockets.set(campaignId, entry)
  }
  entry.refs += 1
  return entry.socket
}

export function releaseSocket(campaignId: string) {
  const entry = sockets.get(campaignId)
  if (!entry) return
  entry.refs -= 1
  if (entry.refs <= 0) {
    entry.socket.close()
    sockets.delete(campaignId)
  }
}
