import { Link, useParams } from 'react-router-dom'
import { useCampaign, useMembers } from '../api/hooks'
import { SceneList } from '../components/SceneList'
import { CharacterList } from '../components/CharacterList'
import { useLiveCache } from '../ws/useLiveCache'

export function LobbyPage() {
  const { cid } = useParams() as { cid: string }
  const { data: campaign, isLoading } = useCampaign(cid)
  const { data: members } = useMembers(cid)
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
        </section>
      </div>
    </div>
  )
}
