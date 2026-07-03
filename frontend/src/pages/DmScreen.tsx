import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useCampaign } from '../api/hooks'
import type { PendingApproval, Scene } from '../api/types'
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
          <h3>Pinned facts</h3>
          <PinnedFactsPanel campaignId={cid} />
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

function PinnedFactsPanel({ campaignId }: { campaignId: string }) {
  const { data: campaign } = useCampaign(campaignId)
  const qc = useQueryClient()
  const [draft, setDraft] = useState('')
  const facts = (campaign?.settings_json.pinned_facts as string[] | undefined) ?? []

  async function save(next: string[]) {
    await api.patch(`/campaigns/${campaignId}`, {
      settings: { ...campaign?.settings_json, pinned_facts: next },
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
