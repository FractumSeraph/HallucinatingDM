import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useCampaign } from '../api/hooks'
import type { Location, PendingApproval, Scene } from '../api/types'
import { useScenes } from '../components/SceneList'
import { DocumentsPanel } from './SearchPage'
import { useLiveCache } from '../ws/useLiveCache'

interface WorldEvent {
  id: string
  description: string
  created_at: string
}

export function DmScreen() {
  const { cid } = useParams() as { cid: string }
  const { data: campaign } = useCampaign(cid)
  useLiveCache(cid)

  if (campaign && campaign.my_role !== 'dm') {
    return <div className="page-pad error-text">The DM screen is for the DM's eyes only.</div>
  }

  return (
    <div className="page-pad container">
      <Link to={`/campaigns/${cid}`}>← {campaign?.name ?? 'Campaign'}</Link>
      <h1>DM screen</h1>
      <div className="sheet-grid">
        <section className="card">
          <h3>AI proposals</h3>
          <ApprovalQueue campaignId={cid} />
        </section>
        <section className="card">
          <h3>Scenes & AI mode</h3>
          <SceneModePanel campaignId={cid} />
        </section>
        <section className="card">
          <h3>Scene prep</h3>
          <ScenePrepPanel campaignId={cid} />
        </section>
        <section className="card">
          <h3>Pinned facts</h3>
          <PinnedFactsPanel campaignId={cid} />
        </section>
        <section className="card">
          <h3>Table content level</h3>
          <ContentLevelPanel campaignId={cid} />
        </section>
        <section className="card">
          <h3>Model &amp; usage</h3>
          <CampaignLlmPanel campaignId={cid} />
        </section>
        <section className="card">
          <h3>World event log</h3>
          <WorldEventFeed campaignId={cid} />
        </section>
        <section className="card">
          <DocumentsPanel campaignId={cid} isDm />
        </section>
      </div>
    </div>
  )
}

function ApprovalQueue({ campaignId }: { campaignId: string }) {
  const qc = useQueryClient()
  const [notes, setNotes] = useState<Record<string, string>>({})
  const { data: approvals } = useQuery<PendingApproval[]>({
    queryKey: ['campaigns', campaignId, 'approvals'],
    queryFn: () => api.get(`/campaigns/${campaignId}/approvals`),
    refetchInterval: 15_000,
  })

  async function act(id: string, action: 'approve' | 'reject') {
    await api.post(`/approvals/${id}/${action}`, action === 'reject' ? { note: notes[id] ?? '' } : {})
    await qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'approvals'] })
  }

  if (!approvals?.length) {
    return <p className="muted">Nothing waiting. The AI will queue drafts and gated actions here.</p>
  }
  return (
    <div className="col">
      {approvals.map((a) => (
        <div key={a.id} className="card" style={{ background: 'var(--bg-inset)' }}>
          {a.kind === 'draft_turn' ? (
            <>
              <span className="badge">draft narration</span>
              {Boolean(a.payload_json.leak_warning) && (
                <span className="badge badge-fail">
                  possible secret leak: {String(a.payload_json.leak_warning)}
                </span>
              )}
              <p style={{ whiteSpace: 'pre-wrap', fontSize: '0.9rem' }}>
                {String(a.payload_json.content ?? '')}
              </p>
            </>
          ) : (
            <>
              <span className="badge">tool: {String(a.payload_json.tool)}</span>
              <pre className="approval-args">
                {JSON.stringify(a.payload_json.arguments, null, 1)}
              </pre>
            </>
          )}
          <input
            placeholder="Rejection note (sent privately to the AI)…"
            value={notes[a.id] ?? ''}
            onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })}
          />
          <div className="row" style={{ marginTop: '0.4rem' }}>
            <button className="btn-primary" onClick={() => act(a.id, 'approve')}>
              Approve
            </button>
            <button className="btn-danger" onClick={() => act(a.id, 'reject')}>
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

function SceneModePanel({ campaignId }: { campaignId: string }) {
  const { data: scenes } = useScenes(campaignId)
  const qc = useQueryClient()

  async function setMode(scene: Scene, dmMode: string) {
    await api.patch(`/scenes/${scene.id}`, { dm_mode: dmMode })
    await qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'scenes'] })
  }

  return (
    <ul className="plain-list">
      {scenes?.map((s) => (
        <li key={s.id} className="row">
          <Link to={`/campaigns/${campaignId}/scenes/${s.id}`} className="grow">
            {s.name}
          </Link>
          <select value={s.dm_mode} onChange={(e) => setMode(s, e.target.value)}>
            <option value="ai">AI runs it</option>
            <option value="copilot">Copilot</option>
            <option value="assist">Assist (approve all)</option>
            <option value="human">Human DM</option>
          </select>
        </li>
      ))}
    </ul>
  )
}

interface ScenePrep {
  dm_notes: string
  time_note: string
  location_id: string | null
}

function ScenePrepPanel({ campaignId }: { campaignId: string }) {
  const { data: scenes } = useScenes(campaignId)
  const [openId, setOpenId] = useState<string | null>(null)

  if (!scenes?.length) return <p className="muted">No scenes yet.</p>
  return (
    <div className="col">
      <p className="muted" style={{ fontSize: '0.82rem', marginTop: 0 }}>
        Secret prep for a scene — notes and the place it happens. The AI honors this and
        reveals it only through play; players never see the notes.
      </p>
      <ul className="plain-list">
        {scenes.map((s) => (
          <li key={s.id} className="col" style={{ gap: '0.4rem' }}>
            <div className="row">
              <span className="grow">{s.name}</span>
              <button onClick={() => setOpenId(openId === s.id ? null : s.id)}>
                {openId === s.id ? 'Close' : 'Prep'}
              </button>
            </div>
            {openId === s.id && (
              <ScenePrepEditor
                campaignId={campaignId}
                sceneId={s.id}
                onSaved={() => setOpenId(null)}
              />
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function ScenePrepEditor({
  campaignId,
  sceneId,
  onSaved,
}: {
  campaignId: string
  sceneId: string
  onSaved: () => void
}) {
  const qc = useQueryClient()
  const { data: prep } = useQuery<ScenePrep>({
    queryKey: ['scenes', sceneId, 'prep'],
    queryFn: () => api.get(`/scenes/${sceneId}/prep`),
  })
  const { data: world } = useQuery<{ locations: Location[] }>({
    queryKey: ['campaigns', campaignId, 'world'],
    queryFn: () => api.get(`/campaigns/${campaignId}/world`),
  })
  const [notes, setNotes] = useState<string | null>(null)
  const [time, setTime] = useState<string | null>(null)
  const [loc, setLoc] = useState<string | null>(null)

  // Seed local state once the current prep loads.
  const notesVal = notes ?? prep?.dm_notes ?? ''
  const timeVal = time ?? prep?.time_note ?? ''
  const locVal = loc ?? prep?.location_id ?? ''

  async function save() {
    await api.patch(`/scenes/${sceneId}`, {
      dm_notes: notesVal,
      time_note: timeVal,
      location_id: locVal, // "" clears
    })
    await qc.invalidateQueries({ queryKey: ['scenes', sceneId, 'prep'] })
    onSaved()
  }

  if (!prep) return <p className="muted">Loading…</p>
  return (
    <div className="card col" style={{ gap: '0.5rem', background: 'var(--bg-inset)' }}>
      <label className="col" style={{ gap: '0.2rem' }}>
        <span className="muted secret-label" style={{ fontSize: '0.8rem' }}>
          🔒 Secret prep notes — dangers, hidden agendas, what waits here
        </span>
        <textarea rows={3} value={notesVal} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <label className="col" style={{ gap: '0.2rem' }}>
        <span className="muted" style={{ fontSize: '0.8rem' }}>
          When (time note)
        </span>
        <input
          value={timeVal}
          placeholder="e.g. dusk, the next morning"
          onChange={(e) => setTime(e.target.value)}
        />
      </label>
      <label className="col" style={{ gap: '0.2rem' }}>
        <span className="muted" style={{ fontSize: '0.8rem' }}>
          Location (bind a place you prepped, so its notes activate here)
        </span>
        <select value={locVal} onChange={(e) => setLoc(e.target.value)}>
          <option value="">— none —</option>
          {world?.locations.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
      </label>
      <div className="row">
        <button className="btn-primary" onClick={save}>
          Save prep
        </button>
      </div>
    </div>
  )
}

interface CampaignLlm {
  base_url: string
  model: string
  toolcall_mode: string
  api_key_set: boolean
  token_cap: number
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number; turns: number }
}

function CampaignLlmPanel({ campaignId }: { campaignId: string }) {
  const qc = useQueryClient()
  const { data } = useQuery<CampaignLlm>({
    queryKey: ['campaigns', campaignId, 'llm'],
    queryFn: () => api.get(`/campaigns/${campaignId}/llm`),
  })
  const [model, setModel] = useState<string | null>(null)
  const [baseUrl, setBaseUrl] = useState<string | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [cap, setCap] = useState<string | null>(null)
  const [status, setStatus] = useState('')

  if (!data) return <p className="muted">Loading…</p>

  const modelVal = model ?? data.model
  const baseVal = baseUrl ?? data.base_url
  const capVal = cap ?? (data.token_cap ? String(data.token_cap) : '')
  const used = data.usage.total_tokens
  const pct = data.token_cap ? Math.min(100, Math.round((used / data.token_cap) * 100)) : 0

  async function save() {
    setStatus('Saving…')
    const body: Record<string, unknown> = {
      model: modelVal,
      base_url: baseVal,
      token_cap: capVal ? Number(capVal) : 0,
    }
    if (apiKey) body.api_key = apiKey
    try {
      await api.put(`/campaigns/${campaignId}/llm`, body)
      setApiKey('')
      await qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'llm'] })
      setStatus('Saved.')
    } catch {
      setStatus('Save failed')
    }
  }

  return (
    <div className="col">
      <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
        Used <strong>{used.toLocaleString()}</strong> tokens over {data.usage.turns} AI turns
        {data.token_cap ? ` · cap ${data.token_cap.toLocaleString()}` : ' · no cap'}.
      </p>
      {data.token_cap > 0 && (
        <div className="usage-bar">
          <div className="usage-bar-fill" style={{ width: `${pct}%` }} />
        </div>
      )}
      <label className="muted" style={{ fontSize: '0.82rem' }}>
        Model override (blank = use the instance default)
        <input value={modelVal} placeholder="qwen3.6-plus" onChange={(e) => setModel(e.target.value)} />
      </label>
      <label className="muted" style={{ fontSize: '0.82rem' }}>
        Endpoint base URL (optional)
        <input
          value={baseVal}
          placeholder="https://opencode.ai/zen/go/v1"
          onChange={(e) => setBaseUrl(e.target.value)}
        />
      </label>
      <label className="muted" style={{ fontSize: '0.82rem' }}>
        API key {data.api_key_set ? '(saved — blank keeps it)' : '(uses shared key if blank)'}
        <input
          type="password"
          value={apiKey}
          placeholder="sk-…"
          onChange={(e) => setApiKey(e.target.value)}
        />
      </label>
      <label className="muted" style={{ fontSize: '0.82rem' }}>
        Token cap (0 = unlimited) — the AI pauses when this campaign hits it
        <input
          type="number"
          value={capVal}
          placeholder="0"
          onChange={(e) => setCap(e.target.value)}
        />
      </label>
      <div className="row">
        <button className="btn-primary" onClick={save}>
          Save
        </button>
        {status && <span className="muted">{status}</span>}
      </div>
    </div>
  )
}

const CONTENT_LEVELS = [
  { value: 'fade-to-black', label: 'Fade to black', hint: 'Bloodless — cut away from anything graphic' },
  { value: 'standard', label: 'Standard fantasy', hint: 'Published-adventure violence (PG-13)' },
  { value: 'grim', label: 'Grim', hint: 'Darker, grittier description' },
]

function ContentLevelPanel({ campaignId }: { campaignId: string }) {
  const { data: campaign } = useCampaign(campaignId)
  const qc = useQueryClient()
  const current = (campaign?.settings_json.content_level as string | undefined) ?? 'standard'

  async function save(level: string) {
    if (!campaign) return // settings not loaded yet — don't clobber them
    await api.patch(`/campaigns/${campaignId}`, {
      settings: { ...campaign.settings_json, content_level: level },
    })
    await qc.invalidateQueries({ queryKey: ['campaigns', campaignId] })
  }

  return (
    <div className="col">
      <p className="muted">
        How graphic the AI DM's violence descriptions may get. This goes into every
        prompt — it sets the tone, and helps stop overcautious models refusing to
        narrate combat.
      </p>
      {CONTENT_LEVELS.map((level) => (
        <label
          key={level.value}
          className="row"
          style={{ alignItems: 'baseline', justifyContent: 'flex-start' }}
        >
          <input
            type="radio"
            name="content-level"
            style={{ width: 'auto' }}
            checked={current === level.value}
            onChange={() => save(level.value)}
          />
          <span>
            <strong>{level.label}</strong>{' '}
            <span className="muted">— {level.hint}</span>
          </span>
        </label>
      ))}
    </div>
  )
}

function PinnedFactsPanel({ campaignId }: { campaignId: string }) {
  const { data: campaign } = useCampaign(campaignId)
  const qc = useQueryClient()
  const [draft, setDraft] = useState('')
  const facts = (campaign?.settings_json.pinned_facts as string[] | undefined) ?? []

  async function save(next: string[]) {
    if (!campaign) return // settings not loaded yet — don't clobber them
    await api.patch(`/campaigns/${campaignId}`, {
      settings: { ...campaign.settings_json, pinned_facts: next },
    })
    await qc.invalidateQueries({ queryKey: ['campaigns', campaignId] })
  }

  return (
    <div className="col">
      {facts.length === 0 && (
        <p className="muted">
          Facts pinned here go into every AI prompt — things the DM must never forget or
          contradict.
        </p>
      )}
      <ul className="plain-list">
        {facts.map((fact, i) => (
          <li key={i} className="row">
            <span className="grow">📌 {fact}</span>
            <button
              className="btn-danger"
              title="Unpin"
              onClick={() => save(facts.filter((_, j) => j !== i))}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault()
          if (!draft.trim()) return
          void save([...facts, draft.trim()])
          setDraft('')
        }}
      >
        <input
          className="grow"
          placeholder="The mayor is secretly a dragon…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button className="btn-primary" type="submit">
          Pin
        </button>
      </form>
    </div>
  )
}

function WorldEventFeed({ campaignId }: { campaignId: string }) {
  const { data: events } = useQuery<WorldEvent[]>({
    queryKey: ['campaigns', campaignId, 'world-events'],
    queryFn: () => api.get(`/campaigns/${campaignId}/world-events`),
  })
  if (!events?.length) return <p className="muted">Nothing has happened… yet.</p>
  return (
    <ul className="plain-list" style={{ fontSize: '0.85rem' }}>
      {events.map((e) => (
        <li key={e.id}>• {e.description}</li>
      ))}
    </ul>
  )
}
