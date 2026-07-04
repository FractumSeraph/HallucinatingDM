/** First-timer help sheet for the game view — opened from the ? button. */
export function HowToPlay({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal card" onClick={(e) => e.stopPropagation()}>
        <h2 style={{ marginTop: 0 }}>How to play</h2>
        <div className="col" style={{ gap: '0.9rem' }}>
          <p style={{ margin: 0 }}>
            <strong>Just say what your character does, in plain words.</strong> "I look
            around." "I ask the innkeeper about the stranger." "I try to pick the lock."
            The DM narrates what happens and handles all the rules for you.
          </p>
          <p style={{ margin: 0 }}>
            <strong>You can try anything.</strong> There's no menu of moves — talk, sneak,
            fight, bargain, climb the chandelier. If the outcome is uncertain, the DM asks
            for a dice roll and a <strong>🎲 Roll button</strong> appears on your message —
            tap it, and the server rolls with your character's real bonuses.
          </p>
          <p style={{ margin: 0 }}>
            <strong>Say what you try, not what happens.</strong> "I swing at the goblin"
            works; "I kill the goblin" doesn't — the dice decide outcomes, and the DM only
            counts gear that's actually on your sheet. Attempts, not results.
          </p>
          <p style={{ margin: 0 }}>
            <strong>Stuck?</strong> Tap <strong>💡</strong> next to the message box for
            three ideas that fit the current moment, or just ask the DM in-game — "what
            are my options?"
          </p>
          <p style={{ margin: 0 }}>
            <strong>Extras:</strong> <strong>🎲</strong> opens quick dice (d20, advantage…),
            or type <code>/roll 2d6+3</code>. Tick <strong>OOC</strong> for table talk the
            DM ignores. Your character sheet (HP, items, gold) updates by itself as you
            play — find it in the campaign lobby.
          </p>
        </div>
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: '1rem' }}>
          <button className="btn-primary" onClick={onClose}>
            Got it
          </button>
        </div>
      </div>
    </div>
  )
}
