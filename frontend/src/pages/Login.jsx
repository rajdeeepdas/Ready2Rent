import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { homeFor, useAuth } from '../auth.jsx'

export default function Login() {
  const { login, status, user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  if (status === 'authed') return <Navigate to={homeFor(user)} replace />

  async function onSubmit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const u = await login(email, password)
      navigate(location.state?.from || homeFor(u), { replace: true })
    } catch (err) {
      setError(err.status === 429 ? 'Too many attempts. Please wait a minute.' : err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card narrow">
      <h1>Log in</h1>
      <form onSubmit={onSubmit}>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
        </label>
        {error && <p className="bad">{error}</p>}
        <button type="submit" className="primary" disabled={busy}>{busy ? 'Signing in…' : 'Log in'}</button>
      </form>
      <p className="muted">New homeowner? <Link to="/register">Create an account</Link></p>
    </div>
  )
}
