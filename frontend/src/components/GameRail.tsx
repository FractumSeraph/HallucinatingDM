import { useState } from 'react'

/** Right rail of the game view: party HP / initiative / my sheet.
 * Party strip lands in Phase 3, combat tracker in Phase 6. */
export function GameRail(_props: { campaignId: string; sceneId: string; isDm: boolean }) {
  const [open, setOpen] = useState(true)
  return (
    <aside className={`game-rail ${open ? '' : 'game-rail-closed'}`}>
      <button className="rail-toggle" onClick={() => setOpen(!open)}>
        {open ? '›' : '‹'}
      </button>
      {open && <p className="muted">Party & combat panels arrive in later phases.</p>}
    </aside>
  )
}
