export interface User {
  id: string
  email: string
  display_name: string
  is_admin: boolean
}

export interface Campaign {
  id: string
  name: string
  description: string
  owner_id: string
  invite_code: string
  settings_json: Record<string, unknown>
  world_clock: string
  my_role: 'dm' | 'player' | null
}

export interface Member {
  user_id: string
  display_name: string
  role: 'dm' | 'player'
}

export interface Scene {
  id: string
  campaign_id: string
  name: string
  kind: 'main' | 'side' | 'solo'
  status: 'active' | 'idle' | 'archived'
  dm_mode: 'human' | 'assist' | 'copilot' | 'ai'
  location_id: string | null
  party_json: string[]
  summary: string
  time_note: string
}

export interface Message {
  id: string
  scene_id: string
  seq: number
  author_type: 'player' | 'dm' | 'ai' | 'system' | 'tool'
  author_user_id: string | null
  character_id: string | null
  kind: 'chat' | 'narration' | 'ooc' | 'roll' | 'tool_result' | 'whisper' | 'system'
  content: string
  payload_json: Record<string, unknown>
  visibility: 'all' | 'dm' | 'dm_ai'
  struck: boolean
  created_at: string
}

export interface DiceRollDetail {
  expression: string
  rolls: number[]
  modifier: number
  total: number
  purpose: string
  roller_name: string
  dc?: number
  outcome?: string
  advantage?: string
  crit?: boolean
}

export interface Character {
  id: string
  campaign_id: string
  user_id: string
  name: string
  race: string
  klass: string
  background: string
  alignment: string
  level: number
  xp: number
  hp_current: number
  hp_max: number
  hp_temp: number
  ac: number
  ability_scores_json: Record<string, number>
  proficiencies_json: {
    skills?: string[]
    saves?: string[]
    expertise?: string[]
    other?: string[]
  }
  spell_slots_json: Record<string, { max: number; used: number }>
  resources_json: Record<string, { max: number; used: number }>
  conditions_json: string[]
  death_saves_json: { successes?: number; failures?: number }
  currency_json: Record<string, number>
  sheet_json: Record<string, unknown>
  notes: string
  status: 'draft' | 'active' | 'retired' | 'dead'
}

export interface InventoryItem {
  entry_id: string
  item_id: string
  name: string
  item_type: string
  rarity: string
  description: string
  quantity: number
  equipped: boolean
}

export interface SrdSummary {
  slug: string
  name: string
}

export interface NPC {
  id: string
  name: string
  role: string
  disposition: string
  description: string
  secrets?: string
  location_id: string | null
  faction_id: string | null
  status: string
  created_by: string
  stat_block_json: Record<string, unknown> | null
}

export interface Monster {
  id: string
  name: string
  cr: string
  description: string
  source: string
  stat_block_json: Record<string, unknown>
}

export interface Location {
  id: string
  parent_id: string | null
  kind: string
  name: string
  description: string
  dm_notes?: string
  tags_json: string[]
  created_by: string
}

export interface Faction {
  id: string
  name: string
  description: string
  goals: string
  dm_notes?: string
}

export interface Quest {
  id: string
  title: string
  status: 'rumored' | 'active' | 'completed' | 'failed'
  summary: string
  dm_notes?: string
  objectives_json: { text: string; done: boolean }[]
  rewards_json: Record<string, unknown>
}

export interface CombatState {
  encounter: {
    id: string
    status: 'setup' | 'active' | 'ended'
    round: number
    active_combatant_id: string | null
  } | null
  combatants: {
    id: string
    ref_type: string
    ref_id: string | null
    name: string
    initiative: number
    hp_current: number | null
    hp_max: number | null
    ac: number | null
    conditions_json: string[]
    defeated: boolean
  }[]
}

export interface DocumentInfo {
  id: string
  title: string
  filename: string
  status: 'processing' | 'ready' | 'error'
  progress: number
  page_count: number
  chunk_count: number
  error: string
}

export interface SearchHit {
  text: string
  document_title: string
  section_path: string
  page_start: number
  page_end: number
  score: number
}

export interface PendingApproval {
  id: string
  scene_id: string
  kind: 'draft_turn' | 'tool_call'
  payload_json: Record<string, unknown>
  status: string
  created_at: string
}

export interface AdminSettings {
  llm_base_url: string
  llm_model: string
  llm_api_key_set: boolean
  llm_toolcall_mode: 'native' | 'prompted' | 'auto'
  embedding_base_url: string
  embedding_model: string
  embedding_api_key_set: boolean
}
