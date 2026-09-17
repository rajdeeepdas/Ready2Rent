import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { homeFor, useAuth } from '../auth.jsx'

export default function Register() {
  const { register, status, user } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ first_name: '', last_name: '', email: '', phone: '', password: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  if (status === 'authed') return <Navigate to={homeFor(user)} replace />

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function onSubmit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await register(form)
      navigate('/app', { replace: true })
    } catch (err) {
      setError(err.status === 429 ? 'Too many attempts. Please wait a minute.' : err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card narrow">
      <h1>Create a homeowner account</h1>
      <p className="muted">Staff accounts are created by an administrator.</p>
      <form onSubmit={onSubmit}>
        <div className="row">
          <label>
            First name
            <input value={form.first_name} onChange={set('first_name')} required autoComplete="given-name" />
          </label>
          <label>
            Last name
            <input value={form.last_name} onChange={set('last_name')} required autoComplete="family-name" />
          </label>
        </div>
        <label>
          Email
          <input type="email" value={form.email} onChange={set('email')} required autoComplete="email" />
        </label>
        <label>
          Phone (optional)
          <input value={form.phone} onChange={set('phone')} autoComplete="tel" />
        </label>
        <label>
          Password
          <input type="password" value={form.password} onChange={set('password')} required minLength={8} autoComplete="new-password" />
        </label>
        {error && <p className="bad">{error}</p>}
        <button type="submit" className="primary" disabled={busy}>{busy ? 'Creating…' : 'Sign up'}</button>
      </form>
      <p className="muted">Already have an account? <Link to="/login">Log in</Link></p>
    </div>
  )
}
