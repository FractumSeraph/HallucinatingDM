import { FormEvent, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { CombatState } from '../api/types'
import { HpBar } from './HpBar'

/** Initiative tracker in the game rail; live via combat.updated events. */
export function CombatPanel({ sceneId, isDm }: { sceneId: string; isDm: boolean }) {
  const qc = useQueryClient()
  const [showStart, setShowStart] = useState(false)
  const { data: combat } = useQuery<CombatState>({
    queryKey: ['scenes', sceneId, 'combat'],
    queryFn: () => api.get(`/scenes/${sceneId}/combat`),
  })

  async function refresh() {
    await qc.invalidateQueries({ queryKey: ['scenes', sceneId, 'combat'] })
  }

  if (!combat?.encounter) {
    if (!isDm) return null
    return (
      <div>
        {showStart ? (
          <StartForm
            sceneId={sceneId}
            onDone={() => {
              setShowStart(false)
              refresh()
            }}
          />
        ) : (
          <button onClick={() => setShowStart(true)}>⚔️ Start combat</button>
        )}
      </div>
    )
  }

  const { encounter, combatants } = combat
  return (
    <div className="combat-panel">
      <h4 style={{ margin: 0 }}>⚔️ Round {encounter.round}</h4>
      <ul className="plain-list" style={{ marginTop: '0.4rem' }}>
        {combatants.map((c) => (
          <li
            key={c.id}
            className={`combatant-row ${c.id === encounter.active_combatant_id ? 'combatant-active' : ''} ${c.defeated ? 'combatant-down' : ''}`}
          >
            <span className="badge">{c.initiative}</span>
            <span className="grow" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {c.name}
              {c.conditions_json.length > 0 && (
                <span className="muted" style={{ fontSize: '0.7rem' }}>
                  {' '}
                  {c.conditions_json.join(', ')}
                </span>
              )}
            </span>
            {c.defeated ? (
              <span className="badge badge-fail">down</span>
            ) : c.hp_current !== null && c.hp_max !== null ? (
              // players see monster health as a bar without numbers via title only for PCs
              c.ref_type === 'character' || isDm ? (
                <HpBar current={c.hp_current} max={c.hp_max} compact />
              ) : (
                <span className="muted" style={{ fontSize: '0.75rem' }}>
                  {healthWord(c.hp_current, c.hp_max)}
                </span>
              )
            ) : null}
          </li>
        ))}
      </ul>
      {isDm && (
        <div className="row" style={{ marginTop: '0.4rem' }}>
          <button
            onClick={async () => {
              await api.post(`/scenes/${sceneId}/combat/next-turn`)
              refresh()
            }}
          >
            Next turn
          </button>
          <button
            className="btn-danger"
            onClick={async () => {
              await api.post(`/scenes/${sceneId}/combat/end`)
              refresh()
            }}
          >
            End
          </button>
        </div>
      )}
    </div>
  )
}

function healthWord(current: number, max: number): string {
  const pct = max > 0 ? current / max : 0
  if (pct >= 1) return 'unharmed'
  if (pct > 0.5) return 'wounded'
  if (pct > 0.15) return 'bloodied'
  return 'near death'
}

function StartForm({ sceneId, onDone }: { sceneId: string; onDone: () => void }) {
  const [text, setText] = useState('')
  const [error, setError] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError('')
    try {
      await api.post(`/scenes/${sceneId}/combat`, {
        participants: text.split(',').map((s) => s.trim()).filter(Boolean),
      })
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
    }
  }

  return (
    <form onSubmit={submit} className="col" style={{ gap: '0.3rem' }}>
      <input
        placeholder="Mira, goblin x3, Mayor Aldric"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {error && <span className="error-text" style={{ fontSize: '0.8rem' }}>{error}</span>}
      <div className="row">
        <button className="btn-primary">Roll initiative</button>
        <button type="button" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}
