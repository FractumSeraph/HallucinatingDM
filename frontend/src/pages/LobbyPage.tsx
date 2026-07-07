import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import { useCampaign, useMe, useMembers, useRecaps } from '../api/hooks'
import { SceneList } from '../components/SceneList'
import { CharacterList, useCharacters } from '../components/CharacterList'
import { useLiveCache } from '../ws/useLiveCache'

export function LobbyPage() {
  const { cid } = useParams() as { cid: string }
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: campaign, isLoading } = useCampaign(cid)
  const { data: members } = useMembers(cid)
  const { data: me } = useMe()
  useLiveCache(cid)

  if (isLoading) return <div className="page-pad muted">Loading…</div>
  if (!campaign) return <div className="page-pad error-text">Campaign not found.</div>

  const isDm = campaign.my_role === 'dm'

  return (
    <div className="page-pad container">
      <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
        <div>
          <h1>{campaign.name}</h1>
          <p className="muted">{campaign.description}</p>
        </div>
        <div className="row">
          {isDm && (
            <Link to={`/campaigns/${cid}/dm`} className="btn">
              DM screen
            </Link>
          )}
          <Link to={`/campaigns/${cid}/world`} className="btn">
            World
          </Link>
          <Link to={`/campaigns/${cid}/search`} className="btn">
            Rules search
          </Link>
        </div>
      </div>

      <FirstStepsBanner campaignId={cid} isDm={isDm} />
      <RecapCard campaignId={cid} />

      <div className="lobby-grid">
        <section className="card">
          <h3>Scenes</h3>
          <SceneList campaignId={cid} isDm={isDm} />
        </section>

        <section className="card">
          <h3>Party</h3>
          <CharacterList campaignId={cid} />
        </section>

        <section className="card">
          <h3>Players</h3>
          <ul className="plain-list">
            {members?.map((m) => (
              <li key={m.user_id} className="row">
                <span className="grow">{m.display_name}</span>
                <span className={`badge badge-${m.role}`}>{m.role.toUpperCase()}</span>
              </li>
            ))}
          </ul>
          {isDm && campaign.invite_code && (
            <p className="muted" style={{ marginTop: '1rem' }}>
              Invite code: <code className="invite-code">{campaign.invite_code}</code>
            </p>
          )}
          {me?.id === campaign.owner_id && (
            <button
              className="btn-danger"
              style={{ marginTop: '1rem' }}
              onClick={async () => {
                const typed = prompt(
                  `This permanently deletes "${campaign.name}" — every scene, chat log, ` +
                    `character, and world entry. There is no undo.\n\nType the campaign ` +
                    `name to confirm:`,
                )
                if (typed === null) return // cancelled — no message needed
                if (typed.trim().toLowerCase() !== campaign.name.trim().toLowerCase()) {
                  alert(`That didn't match "${campaign.name}" — nothing was deleted.`)
                  return
                }
                try {
                  await api.delete(`/campaigns/${cid}`)
                } catch (err) {
                  alert(
                    err instanceof ApiError
                      ? `Delete failed: ${err.message}`
                      : 'Delete failed — check the server logs.',
                  )
                  return
                }
                await qc.invalidateQueries({ queryKey: ['campaigns'] })
                navigate('/campaigns')
              }}
            >
              🗑 Delete campaign
            </button>
          )}
        </section>
      </div>
    </div>
  )
}

function FirstStepsBanner({ campaignId, isDm }: { campaignId: string; isDm: boolean }) {
  const { data: me } = useMe()
  const { data: characters } = useCharacters(campaignId)
  if (isDm || !me || !characters) return null
  const mine = characters.some((c) => c.user_id === me.id && c.status === 'active')
  if (mine) return null
  return (
    <section className="card" style={{ marginTop: '1rem', borderColor: 'var(--accent)' }}>
      <strong>New here? Start by creating your character.</strong>{' '}
      <span className="muted">
        Never played D&D? No problem — describe any hero in plain words ("a shy
        halfling cook who's secretly brave") and the app builds the whole sheet for
        you. Then open a scene and just say what your character does.
      </span>
      <div style={{ marginTop: '0.6rem' }}>
        <Link className="btn btn-primary" to={`/campaigns/${campaignId}/characters/new`}>
          Create your character →
        </Link>
      </div>
    </section>
  )
}

function RecapCard({ campaignId }: { campaignId: string }) {
  const { data } = useRecaps(campaignId)
  if (!data || (!data.campaign_summary && data.recaps.length === 0)) return null
  return (
    <section className="card" style={{ marginTop: '1rem' }}>
      <h3>Previously on…</h3>
      {data.campaign_summary && (
        <p style={{ whiteSpace: 'pre-wrap', fontSize: '0.9rem' }}>{data.campaign_summary}</p>
      )}
      {data.recaps.length > 0 && (
        <ul className="plain-list" style={{ fontSize: '0.85rem' }}>
          {data.recaps.map((r, i) => (
            <li key={i}>
              • {r.content}{' '}
              <span className="muted" style={{ fontSize: '0.75rem' }}>
                ({new Date(r.created_at).toLocaleDateString()})
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
