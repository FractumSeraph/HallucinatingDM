import { FormEvent, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useCampaign } from '../api/hooks'
import type { Faction, Location, Monster, NPC, Quest } from '../api/types'
import { useLiveCache } from '../ws/useLiveCache'

interface World {
  locations: Location[]
  npcs: NPC[]
  factions: Faction[]
  quests: Quest[]
  monsters: Monster[]
}

const TABS = ['Locations', 'NPCs', 'Factions', 'Quests'] as const

export function WorldPage() {
  const { cid } = useParams() as { cid: string }
  const { data: campaign } = useCampaign(cid)
  const [tab, setTab] = useState<(typeof TABS)[number]>('Locations')
  useLiveCache(cid)

  const { data: world, isLoading, isError } = useQuery<World>({
    queryKey: ['campaigns', cid, 'world'],
    queryFn: () => api.get(`/campaigns/${cid}/world`),
  })

  const isDm = campaign?.my_role === 'dm'

  if (isLoading) return <div className="page-pad muted">Loading the world…</div>
  if (isError)
    return (
      <div className="page-pad error-text">
        Couldn't load the world — check your connection and refresh.
      </div>
    )

  return (
    <div className="page-pad container">
      <Link to={`/campaigns/${cid}`}>← {campaign?.name ?? 'Campaign'}</Link>
      <h1>World</h1>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {TABS.map((t) => (
          <button key={t} className={tab === t ? 'btn-primary' : ''} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>

      <div style={{ marginTop: '1rem' }}>
        {tab === 'Locations' && (
          <LocationTree campaignId={cid} locations={world?.locations ?? []} isDm={isDm} />
        )}
        {tab === 'NPCs' && <NpcList campaignId={cid} npcs={world?.npcs ?? []} isDm={isDm} />}
        {tab === 'Factions' && (
          <FactionList campaignId={cid} factions={world?.factions ?? []} isDm={isDm} />
        )}
        {tab === 'Quests' && (
          <QuestList campaignId={cid} quests={world?.quests ?? []} isDm={isDm} />
        )}
      </div>
    </div>
  )
}

// Per-kind field layout for the DM editor. `secret` fields are the 🔒 prep
// only the DM sees and the AI honors; they're the whole point of prepping
// a place and its people before the party arrives.
type EntityRow = Record<string, unknown> & { id?: string }
// The world entity types are readable records; view one as a keyed row for the editor.
const asRow = (o: object): EntityRow => o as unknown as EntityRow

type FieldDef = { key: string; label: string; area?: boolean; secret?: boolean; options?: string[] }
const ENTITY_FIELDS: Record<string, FieldDef[]> = {
  location: [
    { key: 'kind', label: 'Type', options: ['settlement', 'region', 'dungeon', 'building', 'room', 'wilderness', 'world'] },
    { key: 'description', label: 'Description (players may learn this)', area: true },
    { key: 'dm_notes', label: '🔒 Secret DM notes — dangers, twists, what waits here', area: true, secret: true },
  ],
  npc: [
    { key: 'role', label: 'Role / occupation' },
    { key: 'disposition', label: 'Disposition', options: ['friendly', 'neutral', 'wary', 'hostile'] },
    { key: 'description', label: 'Description (players may learn this)', area: true },
    { key: 'secrets', label: "🔒 Secrets — reveal only through play", area: true, secret: true },
  ],
  faction: [
    { key: 'description', label: 'Description', area: true },
    { key: 'goals', label: 'Goals', area: true },
    { key: 'dm_notes', label: '🔒 Secret DM notes', area: true, secret: true },
  ],
  quest: [
    { key: 'status', label: 'Status', options: ['rumored', 'active', 'completed', 'failed'] },
    { key: 'summary', label: 'Summary (the party sees this)', area: true },
    { key: 'dm_notes', label: '🔒 Hidden twist — the truth behind the quest', area: true, secret: true },
  ],
}

/** Create or edit a world entity with all of its DM-only fields. `existing`
 * (with an id) switches the form into edit mode and PATCHes instead. */
function EntityEditor({
  campaignId,
  kind,
  existing,
  onDone,
}: {
  campaignId: string
  kind: string
  existing?: Record<string, unknown> & { id?: string }
  onDone?: () => void
}) {
  const nameKey = kind === 'quest' ? 'title' : 'name'
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = { [nameKey]: String(existing?.[nameKey] ?? '') }
    for (const f of ENTITY_FIELDS[kind]) init[f.key] = String(existing?.[f.key] ?? '')
    return init
  })
  const qc = useQueryClient()
  const editing = Boolean(existing?.id)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!values[nameKey]?.trim()) return
    const fields = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== ''))
    try {
      if (editing) {
        await api.patch(`/world/${kind}/${existing!.id}`, { fields })
      } else {
        await api.post(`/campaigns/${campaignId}/world/${kind}`, { fields })
        setValues((v) => Object.fromEntries(Object.keys(v).map((k) => [k, ''])))
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Saving failed — try again.')
      return
    }
    await qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'world'] })
    onDone?.()
  }

  const set = (k: string, v: string) => setValues((prev) => ({ ...prev, [k]: v }))

  return (
    <form onSubmit={submit} className="card col" style={{ marginTop: '0.75rem', gap: '0.5rem' }}>
      <input
        placeholder={`${kind} ${nameKey}…`}
        value={values[nameKey]}
        onChange={(e) => set(nameKey, e.target.value)}
        required
      />
      {ENTITY_FIELDS[kind].map((f) => (
        <label key={f.key} className="col" style={{ gap: '0.2rem' }}>
          <span className={f.secret ? 'muted secret-label' : 'muted'} style={{ fontSize: '0.8rem' }}>
            {f.label}
          </span>
          {f.options ? (
            <select value={values[f.key]} onChange={(e) => set(f.key, e.target.value)}>
              <option value="">—</option>
              {f.options.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          ) : f.area ? (
            <textarea rows={2} value={values[f.key]} onChange={(e) => set(f.key, e.target.value)} />
          ) : (
            <input value={values[f.key]} onChange={(e) => set(f.key, e.target.value)} />
          )}
        </label>
      ))}
      <div className="row">
        <button className="btn-primary" type="submit">
          {editing ? 'Save' : `Add ${kind}`}
        </button>
        {editing && onDone && (
          <button type="button" onClick={onDone}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}

/** Toggling "＋ Add" / "Edit" affordance wrapping the EntityEditor. */
function EditToggle({
  campaignId,
  kind,
  existing,
  label,
}: {
  campaignId: string
  kind: string
  existing?: Record<string, unknown> & { id?: string }
  label: string
}) {
  const [open, setOpen] = useState(false)
  if (!open)
    return (
      <button className="btn" style={{ marginTop: '0.5rem' }} onClick={() => setOpen(true)}>
        {label}
      </button>
    )
  return (
    <EntityEditor
      campaignId={campaignId}
      kind={kind}
      existing={existing}
      onDone={() => setOpen(false)}
    />
  )
}

function LocationTree({
  campaignId,
  locations,
  isDm,
}: {
  campaignId: string
  locations: Location[]
  isDm: boolean
}) {
  const roots = locations.filter((l) => !l.parent_id)
  const children = (id: string) => locations.filter((l) => l.parent_id === id)

  function render(loc: Location, depth: number) {
    return (
      <div key={loc.id} style={{ marginLeft: depth * 18 }}>
        <div className="card" style={{ marginBottom: 6, padding: '0.5rem 0.9rem' }}>
          <strong>{loc.name}</strong> <span className="badge">{loc.kind}</span>
          {loc.created_by === 'ai' && <span className="badge badge-mode-ai"> AI</span>}
          {loc.description && <p className="muted" style={{ margin: '0.25rem 0 0' }}>{loc.description}</p>}
          {isDm && loc.dm_notes && (
            <p className="muted" style={{ margin: '0.25rem 0 0' }}>
              🔒 {loc.dm_notes}
            </p>
          )}
          {isDm && (
            <EditToggle campaignId={campaignId} kind="location" existing={asRow(loc)} label="Edit" />
          )}
        </div>
        {children(loc.id).map((c) => render(c, depth + 1))}
      </div>
    )
  }

  return (
    <div>
      {locations.length === 0 && (
        <p className="muted">No places charted yet — the AI DM saves everywhere the party goes.</p>
      )}
      {roots.map((l) => render(l, 0))}
      {isDm && <EditToggle campaignId={campaignId} kind="location" label="＋ Add place" />}
    </div>
  )
}

function NpcList({ campaignId, npcs, isDm }: { campaignId: string; npcs: NPC[]; isDm: boolean }) {
  return (
    <div>
      {npcs.length === 0 && <p className="muted">Nobody's been met yet.</p>}
      <div className="campaign-grid">
        {npcs.map((n) => (
          <div key={n.id} className="card">
            <strong>{n.name}</strong>{' '}
            {n.status === 'dead' && <span className="badge badge-fail">dead</span>}
            {n.created_by === 'ai' && <span className="badge badge-mode-ai">AI</span>}
            <div className="muted" style={{ fontSize: '0.85rem' }}>
              {n.role || 'unknown role'} · {n.disposition}
            </div>
            {n.description && <p style={{ fontSize: '0.9rem' }}>{n.description}</p>}
            {isDm && n.secrets && (
              <p className="muted" style={{ fontSize: '0.85rem' }}>
                🔒 {n.secrets}
              </p>
            )}
            {isDm && <EditToggle campaignId={campaignId} kind="npc" existing={asRow(n)} label="Edit" />}
          </div>
        ))}
      </div>
      {isDm && <EditToggle campaignId={campaignId} kind="npc" label="＋ Add NPC" />}
    </div>
  )
}

function FactionList({
  campaignId,
  factions,
  isDm,
}: {
  campaignId: string
  factions: Faction[]
  isDm: boolean
}) {
  return (
    <div>
      {factions.length === 0 && <p className="muted">No factions known.</p>}
      <div className="campaign-grid">
        {factions.map((f) => (
          <div key={f.id} className="card">
            <strong>{f.name}</strong>
            {f.description && <p style={{ fontSize: '0.9rem' }}>{f.description}</p>}
            {f.goals && (
              <p className="muted" style={{ fontSize: '0.85rem' }}>
                Goals: {f.goals}
              </p>
            )}
            {isDm && f.dm_notes && (
              <p className="muted" style={{ fontSize: '0.85rem' }}>
                🔒 {f.dm_notes}
              </p>
            )}
            {isDm && <EditToggle campaignId={campaignId} kind="faction" existing={asRow(f)} label="Edit" />}
          </div>
        ))}
      </div>
      {isDm && <EditToggle campaignId={campaignId} kind="faction" label="＋ Add faction" />}
    </div>
  )
}

const QUEST_ICON: Record<Quest['status'], string> = {
  rumored: '❔',
  active: '🗺️',
  completed: '✅',
  failed: '❌',
}

function QuestList({
  campaignId,
  quests,
  isDm,
}: {
  campaignId: string
  quests: Quest[]
  isDm: boolean
}) {
  return (
    <div className="col" style={{ maxWidth: 700 }}>
      {quests.length === 0 && <p className="muted">The quest log is empty.</p>}
      {quests.map((q) => (
        <div key={q.id} className="card">
          <strong>
            {QUEST_ICON[q.status]} {q.title}
          </strong>{' '}
          <span className="badge">{q.status}</span>
          {q.summary && <p style={{ fontSize: '0.9rem', margin: '0.3rem 0' }}>{q.summary}</p>}
          {q.objectives_json.length > 0 && (
            <ul style={{ margin: '0.3rem 0 0', paddingLeft: '1.2rem' }}>
              {q.objectives_json.map((o, i) => (
                <li key={i} className={o.done ? 'muted' : ''}>
                  {o.done ? '✓ ' : '○ '}
                  {o.text}
                </li>
              ))}
            </ul>
          )}
          {isDm && q.dm_notes && (
            <p className="muted" style={{ fontSize: '0.85rem' }}>
              🔒 {q.dm_notes}
            </p>
          )}
          {isDm && <EditToggle campaignId={campaignId} kind="quest" existing={asRow(q)} label="Edit" />}
        </div>
      ))}
      {isDm && <EditToggle campaignId={campaignId} kind="quest" label="＋ Add quest" />}
    </div>
  )
}
