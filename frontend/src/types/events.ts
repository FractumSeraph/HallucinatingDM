// Mirrors backend app/realtime/events.py — keep event names in sync.
export interface WsEvent<T = Record<string, unknown>> {
  type: string
  campaign_id: string
  scene_id: string | null
  payload: T
  ts: string
}

export const EVT = {
  MESSAGE_CREATED: 'message.created',
  MESSAGE_STRUCK: 'message.struck',
  STREAM_START: 'message.stream.start',
  STREAM_DELTA: 'message.stream.delta',
  STREAM_END: 'message.stream.end',
  ROLL_CREATED: 'roll.created',
  TOOL_ACTIVITY: 'tool.activity',
  CHARACTER_UPDATED: 'character.updated',
  INVENTORY_UPDATED: 'inventory.updated',
  COMBAT_UPDATED: 'combat.updated',
  SCENE_CREATED: 'scene.created',
  SCENE_UPDATED: 'scene.updated',
  QUEST_UPDATED: 'quest.updated',
  WORLD_ENTITY_CHANGED: 'world.entity_changed',
  MEMBER_JOINED: 'campaign.member_joined',
  DM_PROPOSAL: 'dm.proposal',
  DM_WHISPER: 'dm.whisper',
  DOCUMENT_PROGRESS: 'document.ingest_progress',
  AI_STATUS: 'ai.status',
} as const
