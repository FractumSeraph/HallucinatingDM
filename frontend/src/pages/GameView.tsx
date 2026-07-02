import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import { useCampaign } from '../api/hooks'
import type { Message, Scene } from '../api/types'
import { EVT, WsEvent } from '../types/events'
import { useCampaignSocket } from '../ws/useCampaignSocket'
import { MessageRow } from '../components/MessageRow'
import { GameRail } from '../components/GameRail'
import { useLiveCache } from '../ws/useLiveCache'

interface StreamBuffer {
  content: string
}

export function GameView() {
  const { cid, sid } = useParams() as { cid: string; sid: string }
  const { data: campaign } = useCampaign(cid)
  const qc = useQueryClient()
  const [streams, setStreams] = useState<Record<string, StreamBuffer>>({})
  const [aiStatus, setAiStatus] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  useLiveCache(cid)

  const { data: scene } = useQuery<Scene>({
    queryKey: ['scenes', sid],
    queryFn: async () => {
      const scenes = await api.get<Scene[]>(`/campaigns/${cid}/scenes`)
      const found = scenes.find((s) => s.id === sid)
      if (!found) throw new ApiError(404, 'Scene not found')
      return found
    },
  })

  const { data: messages } = useQuery<Message[]>({
    queryKey: ['scenes', sid, 'messages'],
    queryFn: () => api.get(`/scenes/${sid}/messages`),
  })

  function appendMessage(msg: Message) {
    qc.setQueryData<Message[]>(['scenes', sid, 'messages'], (old) => {
      if (!old) return [msg]
      if (old.some((m) => m.id === msg.id)) return old
      return [...old, msg].sort((a, b) => a.seq - b.seq)
    })
  }

  const socket = useCampaignSocket(
    cid,
    (e: WsEvent) => {
      if (e.scene_id && e.scene_id !== sid) return
      switch (e.type) {
        case EVT.MESSAGE_CREATED:
          appendMessage(e.payload as unknown as Message)
          break
        case EVT.STREAM_START: {
          const { stream_id } = e.payload as { stream_id: string }
          setStreams((s) => ({ ...s, [stream_id]: { content: '' } }))
          break
        }
        case EVT.STREAM_DELTA: {
          const { stream_id, delta } = e.payload as { stream_id: string; delta: string }
          setStreams((s) => ({
            ...s,
            [stream_id]: { content: (s[stream_id]?.content ?? '') + delta },
          }))
          break
        }
        case EVT.STREAM_END: {
          const { stream_id, message } = e.payload as {
            stream_id: string
            message: Message | null
          }
          setStreams((s) => {
            const next = { ...s }
            delete next[stream_id]
            return next
          })
          if (message) appendMessage(message)
          break
        }
        case EVT.MESSAGE_STRUCK: {
          const { message_id } = e.payload as { message_id: string }
          qc.setQueryData<Message[]>(['scenes', sid, 'messages'], (old) =>
            old?.map((m) => (m.id === message_id ? { ...m, struck: true } : m)),
          )
          break
        }
        case EVT.AI_STATUS:
          setAiStatus((e.payload as { status: string }).status ?? '')
          break
        case EVT.SCENE_UPDATED:
          qc.setQueryData(['scenes', sid], e.payload as unknown as Scene)
          break
        default:
          break
      }
    },
    () => {
      // reconnect: resync messages from the last seq we have
      qc.invalidateQueries({ queryKey: ['scenes', sid, 'messages'] })
    },
  )

  useEffect(() => {
    if (!socket) return
    socket.subscribeScene(sid)
    return () => socket.unsubscribeScene(sid)
  }, [socket, sid])

  // pin scroll to bottom as content arrives
  const streamText = useMemo(
    () =>
      Object.values(streams)
        .map((s) => s.content)
        .join(''),
    [streams],
  )
  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages?.length, streamText, aiStatus])

  const isDm = campaign?.my_role === 'dm'

  return (
    <div className="game-view">
      <header className="game-header">
        <Link to={`/campaigns/${cid}`}>← {campaign?.name ?? 'Campaign'}</Link>
        <h2 className="grow" style={{ margin: 0 }}>
          {scene?.name}
        </h2>
        {scene && (
          <span className={`badge badge-mode-${scene.dm_mode}`}>
            {scene.dm_mode === 'ai' ? 'AI DM' : scene.dm_mode}
          </span>
        )}
      </header>

      <div className="game-body">
        <div className="game-chat">
          <div className="message-list" ref={listRef}>
            {messages?.map((m) => (
              <MessageRow key={m.id} message={m} />
            ))}
            {Object.entries(streams).map(([id, s]) => (
              <MessageRow
                key={id}
                message={{
                  id,
                  scene_id: sid,
                  seq: 0,
                  author_type: 'ai',
                  author_user_id: null,
                  character_id: null,
                  kind: 'narration',
                  content: s.content || '…',
                  payload_json: {},
                  visibility: 'all',
                  struck: false,
                  created_at: '',
                }}
                streaming
              />
            ))}
            {aiStatus && <div className="ai-status muted">{aiStatus}</div>}
          </div>
          <Composer sceneId={sid} isDm={isDm} />
        </div>
        <GameRail campaignId={cid} sceneId={sid} isDm={isDm} />
      </div>
    </div>
  )
}

function Composer({ sceneId, isDm }: { sceneId: string; isDm: boolean }) {
  const [text, setText] = useState('')
  const [ooc, setOoc] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const content = text.trim()
    if (!content) return
    setBusy(true)
    setError('')
    try {
      if (content.startsWith('/roll ')) {
        await api.post(`/scenes/${sceneId}/roll`, {
          expression: content.slice(6).trim(),
        })
      } else if (content.startsWith('/whisper ') && isDm) {
        await api.post(`/scenes/${sceneId}/whisper`, { content: content.slice(9) })
      } else {
        await api.post(`/scenes/${sceneId}/messages`, {
          content,
          kind: ooc ? 'ooc' : 'chat',
        })
      }
      setText('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to send')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      {error && <div className="error-text">{error}</div>}
      <div className="row">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit(e)
            }
          }}
          placeholder={
            ooc
              ? 'Out-of-character chat…'
              : 'What do you do? (/roll 2d6+3 to roll dice' +
                (isDm ? ', /whisper to instruct the AI privately)' : ')')
          }
          rows={2}
          className="grow"
        />
        <div className="col" style={{ gap: '0.35rem' }}>
          <button className="btn-primary" disabled={busy || !text.trim()}>
            Send
          </button>
          <label className="muted ooc-toggle">
            <input type="checkbox" checked={ooc} onChange={(e) => setOoc(e.target.checked)} />
            OOC
          </label>
        </div>
      </div>
    </form>
  )
}
