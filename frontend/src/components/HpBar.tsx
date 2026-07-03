export function HpBar({
  current,
  max,
  temp = 0,
  compact = false,
}: {
  current: number
  max: number
  temp?: number
  compact?: boolean
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (current / max) * 100)) : 0
  const color = pct > 50 ? 'var(--success)' : pct > 25 ? 'var(--warning)' : 'var(--danger)'
  return (
    <span className={`hp-bar ${compact ? 'hp-bar-compact' : ''}`} title={`${current}/${max} HP`}>
      <span className="hp-bar-fill" style={{ width: `${pct}%`, background: color }} />
      <span className="hp-bar-label">
        {current}/{max}
        {temp > 0 ? ` +${temp}` : ''}
      </span>
    </span>
  )
}
