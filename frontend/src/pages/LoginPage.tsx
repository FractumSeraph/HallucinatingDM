import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import type { User } from '../api/types'

export function LoginPage({ mode }: { mode: 'login' | 'register' }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [signupMode, setSignupMode] = useState<string>('open')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()

  useEffect(() => {
    if (mode === 'register') {
      api
        .get<{ mode: string }>('/auth/registration')
        .then((r) => setSignupMode(r.mode))
        .catch(() => setSignupMode('open'))
    }
  }, [mode])

  const registrationClosed = mode === 'register' && signupMode === 'closed'

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const user =
        mode === 'login'
          ? await api.post<User>('/auth/login', { email, password })
          : await api.post<User>('/auth/register', {
              email,
              password,
              display_name: displayName,
              invite_code: inviteCode,
            })
      qc.setQueryData(['me'], user)
      navigate('/campaigns')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card card">
        <h1>Llamas and Labyrinths</h1>
        <p className="muted">Your table. Your rules. An AI that never sleeps.</p>
        {registrationClosed ? (
          <p className="muted">
            Registration is closed on this instance. Ask the host for access, then{' '}
            <Link to="/login">sign in</Link>.
          </p>
        ) : (
          <form onSubmit={submit} className="col">
            {mode === 'register' && (
              <input
                placeholder="Display name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
                maxLength={80}
              />
            )}
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <input
              type="password"
              placeholder="Password (8+ characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
            {mode === 'register' && signupMode === 'invite' && (
              <input
                placeholder="Invite code (from the host)"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                required
              />
            )}
            {error && <div className="error-text">{error}</div>}
            <button className="btn-primary" disabled={busy}>
              {mode === 'login' ? 'Sign in' : 'Create account'}
            </button>
          </form>
        )}
        <p className="muted">
          {mode === 'login' ? (
            <>
              New here? <Link to="/register">Create an account</Link>
            </>
          ) : (
            <>
              Already have an account? <Link to="/login">Sign in</Link>
            </>
          )}
        </p>
      </div>
    </div>
  )
}
