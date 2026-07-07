import { FormEvent, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import type { Character, InventoryItem } from '../api/types'
import { HpBar } from '../components/HpBar'
import { useCharacters } from '../components/CharacterList'

const ABILITIES = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const

function mod(score: number): string {
  const m = Math.floor((score - 10) / 2)
  return m >= 0 ? `+${m}` : `${m}`
}

export function CharacterSheet() {
  const { cid, charId } = useParams() as { cid: string; charId: string }
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [error, setError] = useState('')

  const { data: c, isError: missing } = useQuery<Character>({
    queryKey: ['characters', charId],
    queryFn: () => api.get(`/characters/${charId}`),
    retry: false,
  })
  const { data: inventory } = useQuery<InventoryItem[]>({
    queryKey: ['characters', charId, 'inventory'],
    queryFn: () => api.get(`/characters/${charId}/inventory`),
  })

  async function patch(body: Record<string, unknown>) {
    setError('')
    try {
      const updated = await api.patch<Character>(`/characters/${charId}`, body)
      qc.setQueryData(['characters', charId], updated)
      qc.invalidateQueries({ queryKey: ['campaigns', cid, 'characters'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Update failed')
    }
  }

  if (missing)
    return (
      <div className="page-pad">
        <p className="error-text">This character no longer exists (deleted or retired?).</p>
        <Link to={`/campaigns/${cid}`}>← Back to campaign</Link>
      </div>
    )
  if (!c) return <div className="page-pad muted">Loading…</div>

  const sheet = c.sheet_json as {
    speed?: number
    traits?: { name: string; description: string }[]
    features?: { name: string; description: string }[]
    personality?: string
    backstory?: string
    spellcasting_ability?: string | null
  }

  return (
    <div className="page-pad container">
      <Link to={`/campaigns/${cid}`}>← Back to campaign</Link>
      <div className="row" style={{ flexWrap: 'wrap', alignItems: 'baseline' }}>
        <h1>{c.name}</h1>
        <span className="muted">
          {c.race} {c.klass} {c.level} · {c.background}
          {c.alignment ? ` · ${c.alignment}` : ''} · {c.xp} XP
        </span>
        {c.status !== 'active' && <span className="badge">{c.status}</span>}
      </div>
      {error && <p className="error-text">{error}</p>}

      <div className="sheet-grid">
        <section className="card">
          <h3>Vitals</h3>
          <HpBar current={c.hp_current} max={c.hp_max} temp={c.hp_temp} />
          <div className="row" style={{ marginTop: '0.5rem' }}>
            <button onClick={() => patch({ hp_current: c.hp_current - 1 })}>−1</button>
            <button onClick={() => patch({ hp_current: c.hp_current + 1 })}>+1</button>
            <button onClick={() => patch({ hp_current: c.hp_max })}>Full heal</button>
          </div>
          <p>
            <strong title="Armor Class — how hard you are to hit. Attacks must roll this or higher.">
              AC
            </strong>{' '}
            {c.ac} · <strong title="How far you can move on your turn">Speed</strong>{' '}
            {sheet.speed ?? 30} ft ·{' '}
            <strong title="Proficiency bonus — added to anything you're trained in">
              Prof
            </strong>{' '}
            +{2 + Math.floor((c.level - 1) / 4)}
          </p>
          <LevelUpButton c={c} charId={charId} cid={cid} />
          {c.conditions_json.length > 0 && (
            <p>
              {c.conditions_json.map((cond) => (
                <span key={cond} className="badge badge-fail" style={{ marginRight: 4 }}>
                  {cond}
                </span>
              ))}
            </p>
          )}
          <h4>Currency</h4>
          <div className="row">
            {(['pp', 'gp', 'sp', 'cp'] as const).map((coin) => (
              <label key={coin} className="muted coin-input">
                {coin.toUpperCase()}
                <input
                  type="number"
                  min={0}
                  value={c.currency_json[coin] ?? 0}
                  onChange={(e) =>
                    patch({ currency: { ...c.currency_json, [coin]: Number(e.target.value) } })
                  }
                />
              </label>
            ))}
          </div>
        </section>

        <section className="card">
          <h3>Abilities</h3>
          <div className="ability-grid">
            {ABILITIES.map((a) => (
              <div key={a} className="ability-tile">
                <span className="ability-name">{a.toUpperCase()}</span>
                <span className="ability-score">{c.ability_scores_json[a]}</span>
                <span className="ability-mod">{mod(c.ability_scores_json[a])}</span>
              </div>
            ))}
          </div>
          <h4 title="Saving throws — dangers you're trained to resist (add your proficiency bonus)">Saves</h4>
          <p className="muted">{c.proficiencies_json.saves?.join(', ').toUpperCase() || '—'}</p>
          <h4>Skills</h4>
          <p className="muted">{c.proficiencies_json.skills?.join(', ') || '—'}</p>
          {Object.keys(c.spell_slots_json).length > 0 && (
            <>
              <h4 title="How many spells of each level you can still cast before resting">Spell slots</h4>
              <div className="row" style={{ flexWrap: 'wrap' }}>
                {Object.entries(c.spell_slots_json).map(([lvl, slot]) => (
                  <span key={lvl} className="badge">
                    L{lvl}: {slot.max - slot.used}/{slot.max}
                  </span>
                ))}
              </div>
            </>
          )}
        </section>

        <section className="card">
          <h3>Inventory</h3>
          <InventoryPanel charId={charId} cid={cid} items={inventory ?? []} />
        </section>

        <section className="card">
          <h3>Features & traits</h3>
          {[...(sheet.traits ?? []), ...(sheet.features ?? [])].map((f) => (
            <details key={f.name}>
              <summary>{f.name}</summary>
              <p className="muted">{f.description}</p>
            </details>
          ))}
          {sheet.personality && (
            <>
              <h4>Personality</h4>
              <p className="muted">{sheet.personality}</p>
            </>
          )}
          {sheet.backstory && (
            <>
              <h4>Backstory</h4>
              <p className="muted">{sheet.backstory}</p>
            </>
          )}
          <h4>Notes</h4>
          <NotesEditor charId={charId} initial={c.notes} onSave={(notes) => patch({ notes })} />
          <div className="row" style={{ marginTop: '1rem' }}>
            {c.status === 'active' && (
              <button
                title="Keep the sheet, but step out of play"
                onClick={() => patch({ status: 'retired' })}
              >
                Retire
              </button>
            )}
            <button
              className="btn-danger"
              onClick={async () => {
                if (
                  !confirm(
                    `Permanently delete ${c.name}? The sheet and inventory are gone ` +
                      `for good (old chat lines keep their text). Consider Retire instead.`,
                  )
                )
                  return
                try {
                  await api.delete(`/characters/${charId}`)
                  qc.invalidateQueries({ queryKey: ['campaigns', cid, 'characters'] })
                  navigate(`/campaigns/${cid}`)
                } catch (err) {
                  setError(err instanceof ApiError ? err.message : 'Delete failed')
                }
              }}
            >
              🗑 Delete
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}

const XP_THRESHOLDS = [
  0, 0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000, 85000, 100000,
  120000, 140000, 165000, 195000, 225000, 265000, 305000, 355000,
]

function LevelUpButton({ c, charId, cid }: { c: Character; charId: string; cid: string }) {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const eligible = c.level < 20 && c.xp >= XP_THRESHOLDS[c.level + 1]
  if (!eligible) {
    const next = c.level < 20 ? XP_THRESHOLDS[c.level + 1] : null
    return next ? (
      <p className="muted" style={{ fontSize: '0.8rem' }}>
        {next - c.xp} XP to level {c.level + 1}
      </p>
    ) : null
  }
  return (
    <div>
      <button
        className="btn-primary"
        onClick={async () => {
          try {
            const updated = await api.post<Character>(`/characters/${charId}/level-up`)
            qc.setQueryData(['characters', charId], updated)
            qc.invalidateQueries({ queryKey: ['campaigns', cid, 'characters'] })
          } catch (err) {
            setError(err instanceof ApiError ? err.message : 'Level up failed')
          }
        }}
      >
        ⬆️ Level up to {c.level + 1}!
      </button>
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}

function InventoryPanel({
  charId,
  cid,
  items,
}: {
  charId: string
  cid: string
  items: InventoryItem[]
}) {
  const [name, setName] = useState('')
  const [qty, setQty] = useState(1)
  const [giving, setGiving] = useState<string | null>(null) // entry_id being given
  const { data: allCharacters } = useCharacters(cid)
  const others = (allCharacters ?? []).filter((c) => c.id !== charId && c.status === 'active')
  const qc = useQueryClient()

  async function refresh() {
    await qc.invalidateQueries({ queryKey: ['characters', charId, 'inventory'] })
  }

  const [invError, setInvError] = useState('')

  async function add(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    setInvError('')
    try {
      await api.post(`/characters/${charId}/inventory`, { name: name.trim(), quantity: qty })
      setName('')
      setQty(1)
      await refresh()
    } catch (err) {
      setInvError(err instanceof Error ? err.message : 'Failed to add item')
    }
  }

  async function setQuantity(entryId: string, quantity: number) {
    setInvError('')
    try {
      await api.patch(`/inventory/${entryId}`, { quantity })
      await refresh()
    } catch (err) {
      setInvError(err instanceof Error ? err.message : 'Failed to update quantity')
    }
  }

  return (
    <div className="col">
      {invError && <p className="error-text">{invError}</p>}
      <ul className="plain-list">
        {items.length === 0 && <li className="muted">Empty pockets.</li>}
        {items.map((it) => (
          <li key={it.entry_id} className="col" style={{ gap: '0.25rem' }}>
            <div className="row">
              <span className="grow">
                {it.name}
                {it.equipped && <span className="badge"> equipped</span>}
              </span>
              <button onClick={() => setQuantity(it.entry_id, it.quantity - 1)}>−</button>
              <span>{it.quantity}</span>
              <button onClick={() => setQuantity(it.entry_id, it.quantity + 1)}>+</button>
              {others.length > 0 && (
                <button
                  title="Give to a party member"
                  aria-label={`Give ${it.name}`}
                  onClick={() => setGiving(giving === it.entry_id ? null : it.entry_id)}
                >
                  🎁
                </button>
              )}
            </div>
            {giving === it.entry_id && (
              <GiveForm
                entry={it}
                others={others}
                onDone={async () => {
                  setGiving(null)
                  await refresh()
                }}
              />
            )}
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="row">
        <input
          placeholder="Add item…"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="grow"
        />
        <input
          type="number"
          min={1}
          value={qty}
          onChange={(e) => setQty(Number(e.target.value))}
          style={{ width: '4.5rem' }}
        />
        <button>Add</button>
      </form>
    </div>
  )
}

function NotesEditor({
  charId,
  initial,
  onSave,
}: {
  charId: string
  initial: string
  onSave: (notes: string) => void
}) {
  const [notes, setNotes] = useState(initial)
  return (
    <div className="col" key={charId}>
      <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
      {notes !== initial && <button onClick={() => onSave(notes)}>Save notes</button>}
    </div>
  )
}


function GiveForm({
  entry,
  others,
  onDone,
}: {
  entry: InventoryItem
  others: { id: string; name: string }[]
  onDone: () => void
}) {
  const [to, setTo] = useState(others[0]?.id ?? '')
  const [amount, setAmount] = useState(1)
  const [error, setError] = useState('')

  return (
    <div className="row" style={{ gap: '0.3rem', flexWrap: 'wrap' }}>
      <select value={to} onChange={(e) => setTo(e.target.value)} style={{ width: 'auto' }}>
        {others.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      <input
        type="number"
        min={1}
        max={entry.quantity}
        value={amount}
        onChange={(e) => setAmount(Number(e.target.value))}
        style={{ width: '4rem' }}
      />
      <button
        className="btn-primary"
        onClick={async () => {
          setError('')
          try {
            await api.post(`/inventory/${entry.entry_id}/give`, {
              to_character_id: to,
              quantity: amount,
            })
            onDone()
          } catch (err) {
            setError(err instanceof ApiError ? err.message : 'Give failed')
          }
        }}
      >
        Give
      </button>
      {error && <span className="error-text" style={{ fontSize: '0.8rem' }}>{error}</span>}
    </div>
  )
}
