import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import { useCampaigns } from '../api/hooks'
import type { Campaign } from '../api/types'

export function CampaignsPage() {
  const { data: campaigns, isLoading } = useCampaigns()
  const [showCreate, setShowCreate] = useState(false)
  const [joinCode, setJoinCode] = useState('')
  const [error, setError] = useState('')
  const qc = useQueryClient()
  const navigate = useNavigate()

  async function join(e: FormEvent) {
    e.preventDefault()
    setError('')
    try {
      const c = await api.post<Campaign>('/campaigns/join', { invite_code: joinCode })
      await qc.invalidateQueries({ queryKey: ['campaigns'] })
      navigate(`/campaigns/${c.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to join')
    }
  }

  return (
    <div className="page-pad container">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h1>Campaigns</h1>
        <button className="btn-primary" onClick={() => setShowCreate(true)}>
          New campaign
        </button>
      </div>

      {isLoading && <p className="muted">Loading…</p>}
      {campaigns?.length === 0 && (
        <p className="muted">No campaigns yet. Create one or join with an invite code.</p>
      )}
      <div className="campaign-grid">
        {campaigns?.map((c) => (
          <Link key={c.id} to={`/campaigns/${c.id}`} className="card campaign-card">
            <h3>{c.name}</h3>
            <p className="muted">{c.description || 'No description'}</p>
            <span className={`badge badge-${c.my_role}`}>{c.my_role?.toUpperCase()}</span>
          </Link>
        ))}
      </div>

      <div className="card" style={{ marginTop: '2rem', maxWidth: 420 }}>
        <h3>Join a campaign</h3>
        <form onSubmit={join} className="row">
          <input
            placeholder="Invite code"
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value)}
            required
          />
          <button>Join</button>
        </form>
        {error && <div className="error-text">{error}</div>}
      </div>

      {showCreate && <CreateCampaignModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}

function CreateCampaignModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [tone, setTone] = useState('heroic fantasy')
  const [beginner, setBeginner] = useState(false)
  const [error, setError] = useState('')
  const qc = useQueryClient()
  const navigate = useNavigate()

  async function submit(e: FormEvent) {
    e.preventDefault()
    try {
      const c = await api.post<Campaign>('/campaigns', {
        name,
        description,
        settings: { tone, beginner_mode: beginner },
      })
      await qc.invalidateQueries({ queryKey: ['campaigns'] })
      navigate(`/campaigns/${c.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create')
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal card" onClick={(e) => e.stopPropagation()}>
        <h2>New campaign</h2>
        <form onSubmit={submit} className="col">
          <input
            placeholder="Campaign name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={120}
          />
          <textarea
            placeholder="Premise / description (the AI DM uses this to set the stage)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
          />
          <label className="muted">
            Tone
            <select value={tone} onChange={(e) => setTone(e.target.value)}>
              <option>heroic fantasy</option>
              <option>grimdark</option>
              <option>comedic</option>
              <option>mystery / intrigue</option>
              <option>horror</option>
              <option>swashbuckling adventure</option>
            </select>
          </label>
          <label className="row muted" style={{ justifyContent: 'flex-start' }}>
            <input
              type="checkbox"
              style={{ width: 'auto' }}
              checked={beginner}
              onChange={(e) => setBeginner(e.target.checked)}
            />
            <span>
              <strong>Beginner table</strong> — we're new to D&D: the DM explains the
              rules in plain words as we play
            </span>
          </label>
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
