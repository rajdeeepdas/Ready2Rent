import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { homeFor, useAuth } from '../auth.jsx'

/**
 * Route guard. `roles` is the list of roles allowed to see the nested routes.
 * Anonymous -> /login (remembering where they were going).
 * Wrong role -> that user's own home. This is UX only; the API enforces the real rule.
 */
export default function RequireRole({ roles }) {
  const { user, status } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <p className="muted">Checking your session…</p>
  if (status === 'anon') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (!roles.includes(user.role)) return <Navigate to={homeFor(user)} replace />
  return <Outlet />
}
