import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import type { Character } from '../api/types'

interface SrdRace {
  slug: string
  name: string
  data: {
    ability_bonuses: { ability: string; bonus: number }[]
    subraces?: { name: string; ability_bonuses?: { ability: string; bonus: number }[] }[]
    speed: number
    traits?: { name: string; description: string }[]
  }
}

interface SrdClass {
  slug: string
  name: string
  data: {
    hit_die: number
    saving_throws: string[]
    spellcasting_ability: string | null
    proficiencies: { skills?: { choose: number; from: string[] } }
    features?: { level: number; name: string; description: string }[]
  }
}

interface ClassInfo {
  is_caster: boolean
  cantrips_known: number
  spells_known: number
  cantrips: string[]
  level1: string[]
  spell_descriptions: Record<string, string>
  starting_kit: { item: string; quantity: number }[]
}

// One-line plain-language skill meanings for total beginners.
const SKILL_HINTS: Record<string, string> = {
  acrobatics: 'Flips, balance, tumbling free',
  'animal handling': 'Calming and controlling animals',
  arcana: 'Knowing about magic and the arcane',
  athletics: 'Climbing, jumping, swimming, grappling',
  deception: 'Lying convincingly',
  history: 'Recalling lore and past events',
  insight: "Reading people's true intentions",
  intimidation: 'Scaring someone into compliance',
  investigation: 'Finding clues and deducing answers',
  medicine: 'Stabilizing the dying, diagnosing illness',
  nature: 'Knowing plants, animals, and weather',
  perception: 'Spotting, hearing, noticing things',
  performance: 'Entertaining a crowd',
  persuasion: 'Winning someone over honestly',
  religion: 'Knowing gods, rites, and holy lore',
  'sleight of hand': 'Pickpocketing and palming objects',
  stealth: 'Sneaking without being seen or heard',
  survival: 'Tracking, foraging, not getting lost',
}

const ABILITIES = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const
const STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]
const POINT_COST: Record<number, number> = { 8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9 }

// Abilities come BEFORE class, so the player picks a class that fits their scores.
const STEPS = ['Race', 'Abilities', 'Class', 'Details', 'Review'] as const

export function CharacterWizard() {
  const { cid } = useParams() as { cid: string }
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [raceSlug, setRaceSlug] = useState('')
  const [subrace, setSubrace] = useState('')
  const [classSlug, setClassSlug] = useState('')
  const [method, setMethod] = useState<'standard' | 'pointbuy' | 'roll'>('standard')
  const [scores, setScores] = useState<Record<string, number>>({
    str: 15, dex: 14, con: 13, int: 12, wis: 10, cha: 8,
  })
  const [rolled, setRolled] = useState(false) // a roll has been made this session
  const [rolling, setRolling] = useState(false)
  const [skills, setSkills] = useState<string[]>([])
  const [cantrips, setCantrips] = useState<string[]>([])
  const [spellsKnown, setSpellsKnown] = useState<string[]>([])
  const [background, setBackground] = useState('acolyte')
  const [alignment, setAlignment] = useState('')
  const [personality, setPersonality] = useState('')
  const [backstory, setBackstory] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const { data: races } = useQuery<SrdRace[]>({
    queryKey: ['srd', 'race', 'full'],
    queryFn: async () => {
      const list = await api.get<{ slug: string }[]>('/srd/race')
      return Promise.all(list.map((r) => api.get<SrdRace>(`/srd/race/${r.slug}`)))
    },
    staleTime: Infinity,
  })
  const { data: classes } = useQuery<SrdClass[]>({
    queryKey: ['srd', 'class', 'full'],
    queryFn: async () => {
      const list = await api.get<{ slug: string }[]>('/srd/class')
      return Promise.all(list.map((c) => api.get<SrdClass>(`/srd/class/${c.slug}`)))
    },
    staleTime: Infinity,
  })
  const { data: backgrounds } = useQuery<{ slug: string; name: string }[]>({
    queryKey: ['srd', 'background'],
    queryFn: () => api.get('/srd/background'),
    staleTime: Infinity,
  })

  const race = races?.find((r) => r.slug === raceSlug)
  const klass = classes?.find((c) => c.slug === classSlug)
  const skillRule = klass?.data.proficiencies?.skills

  const { data: classInfo } = useQuery<ClassInfo>({
    queryKey: ['campaigns', cid, 'class-spells', classSlug],
    queryFn: () => api.get(`/campaigns/${cid}/class-spells/${classSlug}`),
    enabled: Boolean(classSlug),
  })

  // Switching class invalidates prior spell picks.
  useEffect(() => {
    setCantrips([])
    setSpellsKnown([])
  }, [classSlug])

  function toggleFrom(list: string[], set: (v: string[]) => void, value: string, max: number) {
    if (list.includes(value)) set(list.filter((v) => v !== value))
    else if (list.length < max) set([...list, value])
  }

  async function rollAbilities() {
    setRolling(true)
    setError('')
    try {
      const res = await api.post<{ scores: Record<string, number> }>(
        `/campaigns/${cid}/roll-abilities`,
      )
      setScores(res.scores)
      setRolled(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Roll failed')
    } finally {
      setRolling(false)
    }
  }

  const pointsUsed = useMemo(
    () => ABILITIES.reduce((sum, a) => sum + (POINT_COST[scores[a]] ?? 99), 0),
    [scores],
  )
  const arrayValid = useMemo(
    () =>
      [...Object.values(scores)].sort((a, b) => b - a).join(',') ===
      [...STANDARD_ARRAY].sort((a, b) => b - a).join(','),
    [scores],
  )

  function toggleSkill(skill: string) {
    const lower = skill.toLowerCase()
    setSkills((prev) =>
      prev.includes(lower)
        ? prev.filter((s) => s !== lower)
        : prev.length < (skillRule?.choose ?? 0)
          ? [...prev, lower]
          : prev,
    )
  }

  const abilitiesReady =
    method === 'roll' ? rolled : method === 'standard' ? arrayValid : pointsUsed <= 27
  const spellsReady =
    !classInfo?.is_caster ||
    (cantrips.length === classInfo.cantrips_known &&
      spellsKnown.length === classInfo.spells_known)

  const canNext = [
    Boolean(raceSlug),
    abilitiesReady,
    Boolean(classSlug),
    skills.length === (skillRule?.choose ?? 0) && Boolean(name.trim()) && spellsReady,
    true,
  ][step]

  async function submit() {
    setBusy(true)
    setError('')
    try {
      const c = await api.post<Character>(`/campaigns/${cid}/characters`, {
        name: name.trim(),
        race: raceSlug,
        subrace,
        klass: classSlug,
        background,
        alignment,
        method,
        // Rolled scores are made up front now, so send them either way.
        base_scores: scores,
        skill_choices: skills,
        cantrips: classInfo?.is_caster ? cantrips : [],
        spells: classInfo?.is_caster ? spellsKnown : [],
        personality,
        backstory,
      })
      await qc.invalidateQueries({ queryKey: ['campaigns', cid, 'characters'] })
      navigate(`/campaigns/${cid}/characters/${c.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create character')
      setBusy(false)
    }
  }

  const [concept, setConcept] = useState('')
  const [aiBusy, setAiBusy] = useState(false)
  const [aiError, setAiError] = useState('')

  async function suggest() {
    if (!concept.trim()) return
    setAiBusy(true)
    setAiError('')
    try {
      const build = await api.post<{
        name: string
        race: string
        subrace: string
        klass: string
        background: string
        alignment: string
        base_scores: Record<string, number>
        skill_choices: string[]
        personality: string
        backstory: string
      }>(`/campaigns/${cid}/chargen-suggest`, { concept })
      if (races && !races.some((r) => r.slug === build.race)) {
        setAiError(`The AI suggested an unknown race ('${build.race}') — try rephrasing.`)
        return
      }
      if (classes && !classes.some((c) => c.slug === build.klass)) {
        setAiError(`The AI suggested an unknown class ('${build.klass}') — try rephrasing.`)
        return
      }
      setName(build.name)
      setRaceSlug(build.race)
      setSubrace(build.subrace)
      setClassSlug(build.klass)
      setBackground(build.background || 'acolyte')
      setAlignment(build.alignment)
      setMethod('standard')
      setScores(build.base_scores)
      setRolled(true)
      setSkills(build.skill_choices)
      setPersonality(build.personality)
      setBackstory(build.backstory)
      // Land on Details so casters can still pick spells before review.
      setStep(3)
    } catch (err) {
      setAiError(err instanceof ApiError ? err.message : 'Suggestion failed')
    } finally {
      setAiBusy(false)
    }
  }

  return (
    <div className="page-pad container wizard">
      <h1>Create a character</h1>

      <div className="card row" style={{ flexWrap: 'wrap' }}>
        <span>🔮</span>
        <input
          className="grow"
          placeholder='New to D&D? Describe any hero in plain words — "a grumpy dwarf cleric who hates the sea" — and we build the whole sheet.'
          value={concept}
          onChange={(e) => setConcept(e.target.value)}
        />
        <button onClick={suggest} disabled={aiBusy || !concept.trim()}>
          {aiBusy ? 'Consulting the orb…' : 'Suggest build'}
        </button>
        {aiError && <span className="error-text">{aiError}</span>}
      </div>
      <div className="wizard-steps">
        {STEPS.map((label, i) => (
          <button
            key={label}
            className={`wizard-step ${i === step ? 'active' : ''} ${i < step ? 'done' : ''}`}
            onClick={() => i < step && setStep(i)}
          >
            {label}
          </button>
        ))}
      </div>

      {step === 0 && (
        <section className="card">
          <h3>Choose a race</h3>
          <div className="pick-grid">
            {races?.map((r) => (
              <button
                key={r.slug}
                className={`pick ${raceSlug === r.slug ? 'picked' : ''}`}
                onClick={() => {
                  setRaceSlug(r.slug)
                  setSubrace('')
                }}
              >
                <strong>{r.name}</strong>
                <span className="muted">
                  {r.data.ability_bonuses
                    .map((b) => `+${b.bonus} ${b.ability}`)
                    .join(', ')}
                </span>
              </button>
            ))}
          </div>
          {race?.data.subraces && race.data.subraces.length > 0 && (
            <>
              <h4>Subrace</h4>
              <div className="pick-grid">
                <button
                  className={`pick ${subrace === '' ? 'picked' : ''}`}
                  onClick={() => setSubrace('')}
                >
                  <strong>Base {race.name}</strong>
                </button>
                {race.data.subraces.map((s) => (
                  <button
                    key={s.name}
                    className={`pick ${subrace === s.name ? 'picked' : ''}`}
                    onClick={() => setSubrace(s.name)}
                  >
                    <strong>{s.name}</strong>
                    <span className="muted">
                      {(s.ability_bonuses ?? [])
                        .map((b) => `+${b.bonus} ${b.ability}`)
                        .join(', ')}
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
        </section>
      )}

      {step === 1 && (
        <section className="card">
          <h3>Ability scores</h3>
          <p className="muted">
            Six numbers for how good your hero is at things — higher is better.
            Strength (muscle), Dexterity (agility), Constitution (toughness),
            Intelligence (book smarts), Wisdom (awareness), Charisma (presence).
            Set these first — then pick a class that plays to your strengths.
          </p>
          <div className="row" style={{ marginBottom: '1rem' }}>
            {(['standard', 'pointbuy', 'roll'] as const).map((m) => (
              <button
                key={m}
                className={method === m ? 'btn-primary' : ''}
                title={
                  m === 'standard'
                    ? 'Simplest: place six preset numbers where you want them'
                    : m === 'pointbuy'
                      ? 'Build your own spread from a points budget'
                      : 'Let the dice decide — classic and risky'
                }
                onClick={() => {
                  setMethod(m)
                  setRolled(false)
                  if (m === 'standard')
                    setScores({ str: 15, dex: 14, con: 13, int: 12, wis: 10, cha: 8 })
                  if (m === 'pointbuy')
                    setScores({ str: 8, dex: 8, con: 8, int: 8, wis: 8, cha: 8 })
                }}
              >
                {m === 'standard' ? 'Standard array' : m === 'pointbuy' ? 'Point buy' : 'Roll 4d6'}
              </button>
            ))}
          </div>
          {method === 'roll' ? (
            <>
              <div className="row" style={{ marginBottom: '0.75rem' }}>
                <button className="btn-primary" onClick={rollAbilities} disabled={rolling}>
                  {rolling ? 'Rolling…' : rolled ? 'Reroll 4d6' : 'Roll 4d6 (drop lowest)'}
                </button>
                {!rolled && <span className="muted">The dice decide — roll to see your scores.</span>}
              </div>
              {rolled && (
                <div className="ability-grid">
                  {ABILITIES.map((a) => (
                    <div key={a} className="ability-tile">
                      <span className="ability-name">{a.toUpperCase()}</span>
                      <span className="ability-score">{scores[a]}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="ability-grid">
                {ABILITIES.map((a) => (
                  <label key={a} className="ability-input">
                    <span>{a.toUpperCase()}</span>
                    {method === 'standard' ? (
                      <select
                        value={scores[a]}
                        onChange={(e) => setScores({ ...scores, [a]: Number(e.target.value) })}
                      >
                        {STANDARD_ARRAY.map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="number"
                        min={8}
                        max={15}
                        value={scores[a]}
                        onChange={(e) => setScores({ ...scores, [a]: Number(e.target.value) })}
                      />
                    )}
                  </label>
                ))}
              </div>
              {method === 'pointbuy' && (
                <p className={pointsUsed > 27 ? 'error-text' : 'muted'}>
                  Points used: {pointsUsed} / 27
                </p>
              )}
              {method === 'standard' && !arrayValid && (
                <p className="error-text">Use each of 15, 14, 13, 12, 10, 8 exactly once.</p>
              )}
            </>
          )}
        </section>
      )}

      {step === 2 && (
        <section className="card">
          <h3>Choose a class</h3>
          <p className="muted">
            Your job in the party — how you fight, sneak, heal, or cast. Bigger
            hit die (d12 &gt; d6) = tougher; "casts with" tells you which ability
            powers your magic.
          </p>
          <div className="pick-grid">
            {classes?.map((c) => (
              <button
                key={c.slug}
                className={`pick ${classSlug === c.slug ? 'picked' : ''}`}
                onClick={() => {
                  setClassSlug(c.slug)
                  setSkills([])
                }}
              >
                <strong>{c.name}</strong>
                <span
                  className="muted"
                  title={`Hit die d${c.data.hit_die}: health gained per level. Saves: what you're good at resisting.`}
                >
                  d{c.data.hit_die} · saves {c.data.saving_throws.join('/')}
                  {c.data.spellcasting_ability ? ` · casts with ${c.data.spellcasting_ability}` : ''}
                </span>
              </button>
            ))}
          </div>
          {classInfo && classInfo.starting_kit.length > 0 && (
            <div style={{ marginTop: '0.75rem' }}>
              <h4 style={{ margin: '0 0 0.25rem' }}>You'll start with</h4>
              <p className="muted">
                {classInfo.starting_kit
                  .map((k) => (k.quantity > 1 ? `${k.item} ×${k.quantity}` : k.item))
                  .join(', ')}
                {classInfo.is_caster ? ' · plus the spells you choose next' : ''}
              </p>
            </div>
          )}
        </section>
      )}

      {step === 3 && (
        <section className="card col">
          <h3>Identity & background</h3>
          <input
            placeholder="Character name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={80}
          />
          <div className="row">
            <label className="muted grow">
              Background
              <select value={background} onChange={(e) => setBackground(e.target.value)}>
                {backgrounds?.map((b) => (
                  <option key={b.slug} value={b.slug}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="muted grow">
              Alignment
              <select value={alignment} onChange={(e) => setAlignment(e.target.value)}>
                <option value="">Unaligned / undecided</option>
                {['Lawful Good','Neutral Good','Chaotic Good','Lawful Neutral','True Neutral','Chaotic Neutral','Lawful Evil','Neutral Evil','Chaotic Evil'].map((a) => (
                  <option key={a}>{a}</option>
                ))}
              </select>
            </label>
          </div>
          {skillRule && (
            <>
              <h4>
                Class skills — pick {skillRule.choose} ({skills.length} chosen)
              </h4>
              <div className="pick-grid">
                {skillRule.from.map((s) => (
                  <button
                    key={s}
                    className={`pick ${skills.includes(s.toLowerCase()) ? 'picked' : ''}`}
                    title={SKILL_HINTS[s.toLowerCase()]}
                    onClick={() => toggleSkill(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </>
          )}

          {classInfo?.is_caster && (
            <div className="spell-picker">
              <h4 style={{ margin: '0.5rem 0 0.25rem' }}>
                Cantrips — pick {classInfo.cantrips_known} ({cantrips.length} chosen)
              </h4>
              <p className="muted" style={{ margin: '0 0 0.25rem' }}>
                Cantrips are small spells you cast as often as you like;
                level-1 spells are stronger but limited between rests.
              </p>
              <div className="pick-grid">
                {classInfo.cantrips.map((s) => (
                  <button
                    key={s}
                    className={`pick ${cantrips.includes(s) ? 'picked' : ''}`}
                    title={classInfo.spell_descriptions?.[s]}
                    onClick={() => toggleFrom(cantrips, setCantrips, s, classInfo.cantrips_known)}
                  >
                    {s}
                  </button>
                ))}
              </div>
              <h4 style={{ margin: '0.75rem 0 0.25rem' }}>
                Level-1 spells — pick {classInfo.spells_known} ({spellsKnown.length} chosen)
              </h4>
              <div className="pick-grid">
                {classInfo.level1.map((s) => (
                  <button
                    key={s}
                    className={`pick ${spellsKnown.includes(s) ? 'picked' : ''}`}
                    title={classInfo.spell_descriptions?.[s]}
                    onClick={() => toggleFrom(spellsKnown, setSpellsKnown, s, classInfo.spells_known)}
                  >
                    {s}
                  </button>
                ))}
              </div>
              {!spellsReady && (
                <p className="muted">Choose all your cantrips and spells to continue.</p>
              )}
            </div>
          )}

          <textarea
            placeholder="Personality, ideals, bonds, flaws… (the AI DM reads this)"
            value={personality}
            onChange={(e) => setPersonality(e.target.value)}
            rows={2}
          />
          <textarea
            placeholder="Backstory (optional — hooks for the AI DM to weave in)"
            value={backstory}
            onChange={(e) => setBackstory(e.target.value)}
            rows={3}
          />
        </section>
      )}

      {step === 4 && (
        <section className="card">
          <h3>Review</h3>
          <p>
            <strong>{name}</strong> — {subrace || race?.name} {klass?.name}, {background}
            {alignment ? `, ${alignment}` : ''}
          </p>
          <p className="muted">
            {ABILITIES.map((a) => `${a.toUpperCase()} ${scores[a]}`).join(' · ')}
            {method === 'roll' ? ' · rolled 4d6kh3' : ''}
          </p>
          <p className="muted">Skills: {skills.join(', ') || '—'}</p>
          {classInfo && classInfo.starting_kit.length > 0 && (
            <p className="muted">
              Starting gear:{' '}
              {classInfo.starting_kit
                .map((k) => (k.quantity > 1 ? `${k.item} ×${k.quantity}` : k.item))
                .join(', ')}
            </p>
          )}
          {classInfo?.is_caster && (
            <p className="muted">
              Cantrips: {cantrips.join(', ') || '—'} · Spells: {spellsKnown.join(', ') || '—'}
            </p>
          )}
          {error && <p className="error-text">{error}</p>}
        </section>
      )}

      <div className="row" style={{ marginTop: '1rem', justifyContent: 'space-between' }}>
        <button disabled={step === 0} onClick={() => setStep(step - 1)}>
          Back
        </button>
        {step < STEPS.length - 1 ? (
          <button className="btn-primary" disabled={!canNext} onClick={() => setStep(step + 1)}>
            Next
          </button>
        ) : (
          <button className="btn-primary" disabled={busy} onClick={submit}>
            {busy ? 'Creating…' : 'Create character'}
          </button>
        )}
      </div>
    </div>
  )
}
