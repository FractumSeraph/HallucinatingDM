import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import type { Scene } from '../api/types'

const KIND_LABEL: Record<Scene['kind'], string> = {
  main: 'Main table',
  side: 'Side adventure',
  solo: 'Solo adventure',
}

export function useScenes(campaignId: string) {
  return useQuery<Scene[]>({
    queryKey: ['campaigns', campaignId, 'scenes'],
    queryFn: () => api.get(`/campaigns/${campaignId}/scenes`),
  })
}

export function SceneList({ campaignId, isDm }: { campaignId: string; isDm: boolean }) {
  const { data: scenes, isLoading } = useScenes(campaignId)
  const [showCreate, setShowCreate] = useState(false)
  const qc = useQueryClient()

  async function deleteScene(s: Scene) {
    if (
      !confirm(
        `Delete the scene "${s.name}"? Its chat log, rolls, and combat history ` +
          `are gone for good (the campaign's world and recaps survive).`,
      )
    )
      return
    await api.delete(`/scenes/${s.id}`)
    await qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'scenes'] })
  }

  return (
    <div className="col">
      {isLoading && <p className="muted">Loading…</p>}
      {scenes?.length === 0 && (
        <p className="muted">
          No scenes yet. {isDm ? 'Open the main table to begin.' : 'Start a solo adventure!'}
        </p>
      )}
      <ul className="plain-list">
        {scenes?.map((s) => (
          <li key={s.id} className="row" style={{ gap: '0.35rem' }}>
            <Link
              to={`/campaigns/${campaignId}/scenes/${s.id}`}
              className="scene-row grow"
            >
              <span className="grow">
                <strong>{s.name}</strong>
                <span className="muted"> · {KIND_LABEL[s.kind]}</span>
              </span>
              <span className={`badge badge-mode-${s.dm_mode}`}>
                {s.dm_mode === 'ai' ? 'AI DM' : s.dm_mode}
              </span>
              {s.status !== 'active' && <span className="badge">{s.status}</span>}
            </Link>
            {isDm && (
              <button
                className="btn-danger"
                title="Delete this scene and its log (no undo)"
                aria-label={`Delete scene ${s.name}`}
                onClick={() => void deleteScene(s)}
              >
                ✕
              </button>
            )}
          </li>
        ))}
      </ul>
      <button onClick={() => setShowCreate(true)}>
        {isDm ? 'New scene' : 'New solo adventure'}
      </button>
      {showCreate && (
        <CreateSceneModal
          campaignId={campaignId}
          isDm={isDm}
          onClose={() => setShowCreate(false)}
        />
      )}
    </div>
  )
}

function CreateSceneModal({
  campaignId,
  isDm,
  onClose,
}: {
  campaignId: string
  isDm: boolean
  onClose: () => void
}) {
  const [name, setName] = useState('')
  const [kind, setKind] = useState(isDm ? 'main' : 'solo')
  const [dmMode, setDmMode] = useState('ai')
  const [error, setError] = useState('')
  const qc = useQueryClient()
  const navigate = useNavigate()

  async function submit(e: FormEvent) {
    e.preventDefault()
    try {
      const scene = await api.post<Scene>(`/campaigns/${campaignId}/scenes`, {
        name,
        kind,
        dm_mode: isDm ? dmMode : 'ai',
      })
      await qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'scenes'] })
      navigate(`/campaigns/${campaignId}/scenes/${scene.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create scene')
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal card" onClick={(e) => e.stopPropagation()}>
        <h2>{isDm ? 'New scene' : 'New solo adventure'}</h2>
        <form onSubmit={submit} className="col">
          <input
            placeholder="Scene name (e.g. The Rusty Flagon)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={120}
          />
          {isDm && (
            <>
              <label className="muted">
                Kind
                <select value={kind} onChange={(e) => setKind(e.target.value)}>
                  <option value="main">Main table</option>
                  <option value="side">Side adventure</option>
                  <option value="solo">Solo adventure</option>
                </select>
              </label>
              <label className="muted">
                DM mode
                <select value={dmMode} onChange={(e) => setDmMode(e.target.value)}>
                  <option value="ai">AI runs it</option>
                  <option value="copilot">Copilot (AI narrates, DM approves big calls)</option>
                  <option value="assist">Assist (AI drafts, DM approves everything)</option>
                  <option value="human">Human DM (AI on demand)</option>
                </select>
              </label>
            </>
          )}
          {error && <div className="error-text">{error}</div>}
          <div className="row" style={{ justifyContent: 'flex-end' }}>
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button className="btn-primary">Create</button>
          </div>
        </form>
      </div>
    </div>
  )
}
