import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { homeowner } from '../api.js'
import { useAuth } from '../auth.jsx'
import { StatusPill, formatDate } from '../components/status.jsx'

export default function HomeownerHome() {
  const { user } = useAuth()
  const [apps, setApps] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    homeowner.listApplications().then(setApps).catch((e) => setError(e.message))
  }, [])

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Welcome, {user.first_name}</h1>
          <p className="muted">Track your suite legalization from intake to registration.</p>
        </div>
        <Link to="/app/intake" className="button primary">Start a new application</Link>
      </div>

      {error && <p className="bad">{error}</p>}
      {apps === null && !error && <p className="muted">Loading…</p>}

      {apps && apps.length === 0 && (
        <div className="card">
          <h2>No applications yet</h2>
          <p>
            Tell us about your property and suite. It takes about five minutes, and you can upload
            documents afterwards.
          </p>
          <Link to="/app/intake" className="button primary">Start your intake</Link>
        </div>
      )}

      {apps && apps.map((a) => (
        <Link key={a.id} to={`/app/applications/${a.id}`} className="card link-card">
          <div className="card-row">
            <div>
              <strong>{a.street_address}</strong>
              <div className="muted">
                {a.suite_type === 'new' ? 'New suite' : 'Legalize existing suite'} · submitted {formatDate(a.submitted_at)}
              </div>
            </div>
            <div className="right">
              <StatusPill status={a.status} label={a.status_display} />
              <div className="muted">Documents: {a.documents_uploaded}/{a.documents_required}</div>
            </div>
          </div>
        </Link>
      ))}
    </>
  )
}
