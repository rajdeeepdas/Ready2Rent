import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { homeFor, isOps, useAuth } from '../auth.jsx'

export default function Layout() {
  const { user, status, logout } = useAuth()
  const navigate = useNavigate()

  async function onLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <>
      <header className="topbar">
        <Link to={user ? homeFor(user) : '/'} className="brand">
          <img src="/ready2rent-icon.svg" alt="" width="22" height="22" className="brand-icon" />
          Ready2Rent
        </Link>
        <nav>
          {status === 'authed' ? (
            <>
              <NavLink to={homeFor(user)} end>{isOps(user) ? 'Lead queue' : 'Home'}</NavLink>
              {/* Internal ops tool: only staff and admin see it (the API enforces the same rule). */}
              {isOps(user) && <NavLink to="/health">System health</NavLink>}
              <span className="who">
                {user.email} <span className={`pill pill-${user.role}`}>{user.role}</span>
              </span>
              <button onClick={onLogout}>Log out</button>
            </>
          ) : (
            <>
              <NavLink to="/login">Log in</NavLink>
              <NavLink to="/register">Sign up</NavLink>
            </>
          )}
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  )
}
