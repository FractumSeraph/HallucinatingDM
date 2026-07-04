import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Quest } from '../api/types'
import { useCharacters } from './CharacterList'
import { HpBar } from './HpBar'
import { CombatPanel } from './CombatPanel'

/** Right rail of the game view: party HP, combat tracker, quest log. */
export function GameRail({
  campaignId,
  sceneId,
  isDm,
}: {
  campaignId: string
  sceneId: string
  isDm: boolean
}) {
  const [open, setOpen] = useState(window.innerWidth > 820)
  const { data: characters } = useCharacters(campaignId)
  const active = characters?.filter((c) => c.status === 'active')

  return (
    <>
      {open && <div className="rail-backdrop" onClick={() => setOpen(false)} />}
      <aside className={`game-rail ${open ? '' : 'game-rail-closed'}`}>
        <button
          className="rail-toggle"
          aria-label={open ? 'Hide party panel' : 'Show party panel'}
          onClick={() => setOpen(!open)}
        >
          {open ? '›' : '⚔️'}
        </button>
        {open && (
          <div className="col">
            <CombatPanel sceneId={sceneId} isDm={isDm} />
            <h4 style={{ margin: '0.5rem 0 0' }}>Party</h4>
            {active?.length === 0 && <p className="muted">No active characters.</p>}
            {active?.map((c) => (
              <Link
                key={c.id}
                to={`/campaigns/${campaignId}/characters/${c.id}`}
                className="party-row"
              >
                <span className="grow">
                  <strong>{c.name}</strong>
                  <div className="muted" style={{ fontSize: '0.78rem' }}>
                    {c.race} {c.klass} {c.level} · AC {c.ac}
                  </div>
                </span>
                <HpBar current={c.hp_current} max={c.hp_max} temp={c.hp_temp} compact />
              </Link>
            ))}
            <QuestLog campaignId={campaignId} />
          </div>
        )}
      </aside>
    </>
  )
}

/** Open quests with objective ticks — updated live via QUEST_UPDATED events. */
function QuestLog({ campaignId }: { campaignId: string }) {
  const { data: quests } = useQuery<Quest[]>({
    queryKey: ['campaigns', campaignId, 'quests'],
    queryFn: () => api.get(`/campaigns/${campaignId}/quests`),
  })
  const open = quests?.filter((q) => q.status === 'active' || q.status === 'rumored')
  if (!open?.length) return null
  return (
    <>
      <h4 style={{ margin: '0.5rem 0 0' }}>Quests</h4>
      {open.map((q) => (
        <div key={q.id} className="quest-row">
          <div className="row" style={{ gap: '0.4rem' }}>
            <strong className="grow">{q.title}</strong>
            {q.status === 'rumored' && <span className="badge">rumored</span>}
          </div>
          {q.summary && <div className="muted quest-summary">{q.summary}</div>}
          {q.objectives_json.length > 0 && (
            <ul className="plain-list quest-objectives">
              {q.objectives_json.map((o, i) => (
                <li key={i} className={o.done ? 'objective-done' : ''}>
                  {o.done ? '✓' : '○'} {o.text}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </>
  )
}
