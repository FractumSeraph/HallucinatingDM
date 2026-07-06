import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useCampaign, useMe, useMembers, useRecaps } from '../api/hooks'
import { SceneList } from '../components/SceneList'
import { CharacterList } from '../components/CharacterList'
import { useLiveCache } from '../ws/useLiveCache'

export function LobbyPage() {
  const { cid } = useParams() as { cid: string }
  const navigate = useNavigate()
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
                if (typed !== campaign.name) return
                await api.delete(`/campaigns/${cid}`)
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
            <li key={i}>• {r.content}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
