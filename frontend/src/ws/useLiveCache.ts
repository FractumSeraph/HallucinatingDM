import { useQueryClient } from '@tanstack/react-query'
import type { Character, Scene } from '../api/types'
import { EVT, WsEvent } from '../types/events'
import { useCampaignSocket } from './useCampaignSocket'

/**
 * Keeps campaign-scoped query caches (characters, scenes, inventory, quests…)
 * fresh from WebSocket events. Mount once per campaign-scoped page.
 */
export function useLiveCache(campaignId: string | undefined) {
  const qc = useQueryClient()

  // Events missed while disconnected (phone backgrounded, dropped wifi) are
  // gone for good — resync every live cache from REST on reconnect so combat
  // trackers, HP bars, and quests don't stay frozen at pre-drop values.
  const resync = () => {
    if (!campaignId) return
    qc.invalidateQueries({ queryKey: ['campaigns', campaignId] })
    qc.invalidateQueries({ queryKey: ['scenes'] })
    qc.invalidateQueries({ queryKey: ['characters'] })
  }

  return useCampaignSocket(campaignId, (e: WsEvent) => {
    if (!campaignId) return
    switch (e.type) {
      case EVT.CHARACTER_UPDATED: {
        const character = e.payload as unknown as Character
        qc.setQueryData<Character[]>(['campaigns', campaignId, 'characters'], (old) => {
          if (!old) return old
          const idx = old.findIndex((c) => c.id === character.id)
          if (idx === -1) return [...old, character]
          const next = [...old]
          next[idx] = character
          return next
        })
        qc.setQueryData(['characters', character.id], character)
        break
      }
      case EVT.INVENTORY_UPDATED: {
        const { character_id } = e.payload as { character_id: string }
        qc.invalidateQueries({ queryKey: ['characters', character_id, 'inventory'] })
        break
      }
      case EVT.SCENE_CREATED:
      case EVT.SCENE_UPDATED: {
        const scene = e.payload as unknown as Scene
        qc.setQueryData<Scene[]>(['campaigns', campaignId, 'scenes'], (old) => {
          if (!old) return old
          const idx = old.findIndex((s) => s.id === scene.id)
          if (idx === -1) return [...old, scene]
          const next = [...old]
          next[idx] = scene
          return next
        })
        // Scene updates also fire when recaps are (re)written — keep "Previously on…" live.
        qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'recaps'] })
        break
      }
      case EVT.COMBAT_UPDATED: {
        if (e.scene_id) {
          qc.setQueryData(['scenes', e.scene_id, 'combat'], e.payload)
        }
        break
      }
      case EVT.QUEST_UPDATED:
        qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'quests'] })
        break
      case EVT.WORLD_ENTITY_CHANGED:
        qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'world'] })
        break
      case EVT.DM_PROPOSAL:
        qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'approvals'] })
        break
      case EVT.DOCUMENT_PROGRESS:
        qc.invalidateQueries({ queryKey: ['campaigns', campaignId, 'documents'] })
        break
      default:
        break
    }
  }, resync)
}
