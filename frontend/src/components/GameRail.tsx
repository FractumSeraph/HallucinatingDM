import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useCharacters } from './CharacterList'
import { HpBar } from './HpBar'
import { CombatPanel } from './CombatPanel'

/** Right rail of the game view: party HP, combat tracker. */
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
    <aside className={`game-rail ${open ? '' : 'game-rail-closed'}`}>
      <button className="rail-toggle" onClick={() => setOpen(!open)}>
        {open ? '›' : '‹'}
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
        </div>
      )}
    </aside>
  )
}
