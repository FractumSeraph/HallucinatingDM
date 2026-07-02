import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Character } from '../api/types'
import { HpBar } from './HpBar'

export function useCharacters(campaignId: string) {
  return useQuery<Character[]>({
    queryKey: ['campaigns', campaignId, 'characters'],
    queryFn: () => api.get(`/campaigns/${campaignId}/characters`),
  })
}

export function CharacterList({ campaignId }: { campaignId: string }) {
  const { data: characters, isLoading } = useCharacters(campaignId)

  return (
    <div className="col">
      {isLoading && <p className="muted">Loading…</p>}
      {characters?.length === 0 && <p className="muted">No characters yet.</p>}
      <ul className="plain-list">
        {characters?.map((c) => (
          <li key={c.id}>
            <Link to={`/campaigns/${campaignId}/characters/${c.id}`} className="scene-row">
              <span className="grow">
                <strong>{c.name}</strong>
                <span className="muted">
                  {' '}
                  · {c.race} {c.klass} {c.level}
                </span>
              </span>
              {c.status !== 'active' && <span className="badge">{c.status}</span>}
              <HpBar current={c.hp_current} max={c.hp_max} temp={c.hp_temp} compact />
            </Link>
          </li>
        ))}
      </ul>
      <Link to={`/campaigns/${campaignId}/characters/new`} className="btn" style={{ textAlign: 'center' }}>
        Create character
      </Link>
    </div>
  )
}
