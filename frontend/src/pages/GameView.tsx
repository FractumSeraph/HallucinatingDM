import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import { useCampaign, useMe } from '../api/hooks'
import type { Message, Scene } from '../api/types'
import { EVT, WsEvent } from '../types/events'
import { useCampaignSocket } from '../ws/useCampaignSocket'
import { MessageRow } from '../components/MessageRow'
import { GameRail } from '../components/GameRail'
import { HowToPlay } from '../components/HowToPlay'
import { useCharacters } from '../components/CharacterList'
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
  const [showHelp, setShowHelp] = useState(false)
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
    // tail=true loads the most recent window, not the oldest — so opening a
    // long-running scene lands you at the current moment.
    queryFn: () => api.get(`/scenes/${sid}/messages?tail=true&limit=500`),
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
  const { data: me } = useMe()
  const { data: allCharacters } = useCharacters(cid)
  // Speak and roll as your own active character so everyone (including the
  // AI) sees "Mira", not an anonymous player.
  const myCharacterId = allCharacters?.find(
    (c) => c.user_id === me?.id && c.status === 'active',
  )?.id

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
        {scene && scene.dm_mode !== 'human' && (
          <button
            title="Ask the AI DM to continue"
            onClick={() => api.post(`/scenes/${sid}/nudge`).catch(() => {})}
          >
            ✨<span className="hide-sm"> Continue</span>
          </button>
        )}
        {isDm && (
          <button
            className="btn-danger"
            title="Strike the last AI turn and reverse its effects"
            onClick={() => {
              if (confirm('Undo the last AI turn? Its messages are struck and state changes reversed.'))
                api.post(`/scenes/${sid}/retcon-last-turn`).catch(() => {})
            }}
          >
            ⎌<span className="hide-sm"> Retcon</span>
          </button>
        )}
        <a
          className="btn"
          href={`/api/v1/scenes/${sid}/transcript`}
          title="Download the full scene log"
          aria-label="Download scene log"
        >
          ⬇<span className="hide-sm"> Log</span>
        </a>
        <button title="How to play" aria-label="How to play" onClick={() => setShowHelp(true)}>
          ?
        </button>
      </header>
      {showHelp && <HowToPlay onClose={() => setShowHelp(false)} />}

      <div className="game-body">
        <div className="game-chat">
          <div className="message-list" ref={listRef}>
            {messages && messages.length === 0 && Object.keys(streams).length === 0 && (
              <div className="card starter-hint muted">
                <strong>The scene is set — you go first.</strong> Describe what your
                character does, in plain words: <em>"I look around"</em>, <em>"I talk to
                the innkeeper"</em>. The DM handles the rules. Stuck? Tap 💡 below for
                ideas, or ? above for a quick guide.
              </div>
            )}
            {messages?.map((m) => (
              <MessageRow
                key={m.id}
                message={m}
                onRespondRoll={(messageId) =>
                  api.post(`/scenes/${sid}/respond-roll`, { message_id: messageId }).catch(() => {})
                }
              />
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
          <Composer sceneId={sid} isDm={isDm} characterId={myCharacterId} />
        </div>
        <GameRail campaignId={cid} sceneId={sid} isDm={isDm} />
      </div>
    </div>
  )
}

const QUICK_ROLLS: [string, string][] = [
  ['d20', '1d20'],
  ['Advantage', '2d20kh1'],
  ['Disadvantage', '2d20kl1'],
  ['d4', '1d4'],
  ['d6', '1d6'],
  ['d8', '1d8'],
  ['d10', '1d10'],
  ['d12', '1d12'],
  ['d100', '1d100'],
]

function Composer({
  sceneId,
  isDm,
  characterId,
}: {
  sceneId: string
  isDm: boolean
  characterId?: string
}) {
  const [text, setText] = useState('')
  const [ooc, setOoc] = useState(false)
  const [showDice, setShowDice] = useState(false)
  const [ideas, setIdeas] = useState<string[]>([])
  const [ideasBusy, setIdeasBusy] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function fetchIdeas() {
    if (ideasBusy) return
    setIdeasBusy(true)
    setError('')
    try {
      const res = await api.post<{ suggestions: string[] }>(
        `/scenes/${sceneId}/suggest-actions`,
      )
      setIdeas(res.suggestions)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'No ideas right now — try anything!')
    } finally {
      setIdeasBusy(false)
    }
  }

  async function quickRoll(expression: string) {
    setError('')
    try {
      await api.post(`/scenes/${sceneId}/roll`, {
        expression,
        character_id: characterId ?? null,
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Roll failed')
    }
  }

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
          character_id: characterId ?? null,
        })
      } else if (content.startsWith('/whisper ') && isDm) {
        await api.post(`/scenes/${sceneId}/whisper`, { content: content.slice(9) })
      } else {
        await api.post(`/scenes/${sceneId}/messages`, {
          content,
          kind: ooc ? 'ooc' : 'chat',
          character_id: ooc ? null : characterId ?? null,
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
      {ideas.length > 0 && (
        <div className="idea-chips">
          {ideas.map((s) => (
            <button
              key={s}
              type="button"
              title="Use this as a starting point — edit before sending"
              onClick={() => {
                setText(s)
                setIdeas([])
              }}
            >
              💡 {s}
            </button>
          ))}
          <button type="button" className="idea-dismiss" onClick={() => setIdeas([])}>
            ✕
          </button>
        </div>
      )}
      {showDice && (
        <div className="dice-bar">
          {QUICK_ROLLS.map(([label, expression]) => (
            <button
              key={label}
              type="button"
              disabled={busy}
              onClick={() => quickRoll(expression)}
            >
              {label}
            </button>
          ))}
        </div>
      )}
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
          <div className="row" style={{ gap: '0.4rem' }}>
            <button
              type="button"
              className="dice-toggle"
              title="Stuck? Get three ideas for what to do"
              aria-label="Suggest actions"
              disabled={ideasBusy}
              onClick={fetchIdeas}
            >
              {ideasBusy ? '…' : '💡'}
            </button>
            <button
              type="button"
              className={showDice ? 'dice-toggle dice-toggle-on' : 'dice-toggle'}
              title="Quick dice rolls"
              aria-label="Quick dice rolls"
              onClick={() => setShowDice(!showDice)}
            >
              🎲
            </button>
            <label className="muted ooc-toggle">
              <input type="checkbox" checked={ooc} onChange={(e) => setOoc(e.target.checked)} />
              OOC
            </label>
          </div>
        </div>
      </div>
    </form>
  )
}
