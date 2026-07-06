import type { DiceRollDetail, Message } from '../api/types'
import { renderMarkdown } from '../lib/md'

const AUTHOR_ICON: Record<Message['author_type'], string> = {
  player: '🗡️',
  dm: '👑',
  ai: '🔮',
  system: '⚙️',
  tool: '🧰',
}

export function MessageRow({
  message,
  speaker,
  streaming = false,
  onRespondRoll,
}: {
  message: Message
  /** Who's talking — the character's name (or "DM") shown above the text so
   *  players can tell each other apart at a multiplayer table. */
  speaker?: string
  streaming?: boolean
  onRespondRoll?: (messageId: string) => void
}) {
  if (message.kind === 'roll') {
    return <RollCard message={message} />
  }

  const rollRequest = message.payload_json.roll_request as
    | { character_id: string; kind: string; ability_or_skill: string; dc?: number }
    | undefined
  const answered = Boolean(message.payload_json.answered)

  const classes = [
    'msg',
    `msg-${message.author_type}`,
    `msg-kind-${message.kind}`,
    message.struck ? 'msg-struck' : '',
    streaming ? 'msg-streaming' : '',
    message.visibility !== 'all' ? 'msg-private' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={classes}>
      <span className="msg-icon" title={message.author_type}>
        {AUTHOR_ICON[message.author_type]}
      </span>
      <div className="msg-body">
        {speaker && <span className="msg-speaker">{speaker}</span>}
        {message.visibility !== 'all' && <span className="badge">DM only</span>}
        {message.kind === 'ooc' && <span className="badge">OOC</span>}
        <span
          dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
        />
        {streaming && <span className="cursor-blink">▍</span>}
        {rollRequest && onRespondRoll && !answered && !message.struck && (
          <div style={{ marginTop: '0.35rem' }}>
            <button className="btn-primary" onClick={() => onRespondRoll(message.id)}>
              🎲 Roll {rollRequest.ability_or_skill} {rollRequest.kind}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function RollCard({ message }: { message: Message }) {
  const roll = message.payload_json.roll as DiceRollDetail | undefined
  if (!roll) return null
  const outcome = roll.outcome
  return (
    <div className="msg msg-roll">
      <span className="msg-icon">🎲</span>
      <div className="msg-body">
        <strong>{roll.roller_name || 'Someone'}</strong>{' '}
        <span className="muted">
          rolls {roll.expression}
          {roll.purpose !== 'raw' ? ` (${roll.purpose})` : ''}
          {roll.advantage && roll.advantage !== 'none'
            ? roll.advantage === 'adv'
              ? ' with advantage'
              : ' with disadvantage'
            : ''}
        </span>
        <div className="dice-row">
          {roll.rolls.map((face, i) => (
            <span key={i} className={`die ${face === 20 ? 'die-crit' : face === 1 ? 'die-fumble' : ''}`}>
              {face}
            </span>
          ))}
          {roll.modifier !== 0 && (
            <span className="muted">
              {roll.modifier > 0 ? `+${roll.modifier}` : roll.modifier}
            </span>
          )}
          <span className="roll-total">= {roll.total}</span>
          {roll.dc !== undefined && (
            <span className={`badge ${outcome === 'success' ? 'badge-success' : 'badge-fail'}`}>
              DC {roll.dc} · {outcome}
            </span>
          )}
          {roll.crit && <span className="badge badge-success">CRIT</span>}
        </div>
      </div>
    </div>
  )
}
