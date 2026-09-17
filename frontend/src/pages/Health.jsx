import { useCallback, useEffect, useState } from 'react'
import { API_BASE_URL, getHealth } from '../api.js'

function Row({ label, value }) {
  const ok = value === 'ok'
  return (
    <div className="status">
      <span>{label}</span>
      <span className={ok ? 'ok' : 'bad'}>{String(value)}</span>
    </div>
  )
}

export default function Health() {
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setHealth(await getHealth())
    } catch (e) {
      if (e.status === 503 && e.body) setHealth(e.body) // degraded still carries the per-check body
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <>
      <h1>System health</h1>
      <p className="muted">
        Internal ops tool (staff and admin only). API base: <code>{API_BASE_URL || '(same origin, /api proxied)'}</code>
      </p>
      <div className="card">
        {loading && <p>Checking…</p>}
        {error && <p className="bad">Could not reach the API: {error}</p>}
        {health && (
          <>
            <Row label="API" value={health.status} />
            <Row label="PostgreSQL" value={health.checks?.database} />
            <Row label="Redis" value={health.checks?.redis} />
            <p className="muted">Django {health.version?.django} · checked at {health.timestamp}</p>
          </>
        )}
        <button onClick={load} disabled={loading}>Re-check</button>
      </div>
    </>
  )
}
