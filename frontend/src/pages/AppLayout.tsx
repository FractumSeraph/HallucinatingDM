import { Link, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useLogout, useMe } from '../api/hooks'

export function AppLayout() {
  const { data: me, isLoading } = useMe()
  const logout = useLogout()
  const location = useLocation()

  if (isLoading) return <div className="page-pad muted">Loading…</div>
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/campaigns" className="brand">
          🎲 HallucinatingDM
        </Link>
        <div className="row">
          {me.is_admin && (
            <Link to="/admin" className="muted">
              Admin
            </Link>
          )}
          <span className="muted">{me.display_name}</span>
          <button onClick={() => logout.mutate()}>Sign out</button>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
