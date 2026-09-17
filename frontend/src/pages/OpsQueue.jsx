import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ops } from '../api.js'
import { useAuth } from '../auth.jsx'
import { StatusPill, formatDate } from '../components/status.jsx'

export default function OpsQueue() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const [options, setOptions] = useState(null)
  const [summary, setSummary] = useState(null)
  const [page, setPage] = useState(null)
  const [error, setError] = useState(null)
  const [q, setQ] = useState(params.get('q') || '')

  const filters = {
    status: params.get('status') || '',
    assigned: params.get('assigned') || '',
    suite_type: params.get('suite_type') || '',
    q: params.get('q') || '',
    ordering: params.get('ordering') || '-created_at',
    page: params.get('page') || '',
  }

  const setFilter = (key, value) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.delete('page')
    setParams(next)
  }

  const load = useCallback(async () => {
    setError(null)
    try {
      const [o, s, p] = await Promise.all([options || ops.options(), ops.summary(), ops.queue(filters)])
      setOptions(o)
      setSummary(s)
      setPage(p)
    } catch (e) {
      setError(e.message)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params])

  useEffect(() => {
    load()
  }, [load])

  const pageNum = Number(filters.page || 1)
  const pageSize = 25
  const total = page?.count || 0
  const lastPage = Math.max(1, Math.ceil(total / pageSize))

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Lead queue</h1>
          <p className="muted">Signed in as {user.email} ({user.role}).</p>
        </div>
        {summary && (
          <div className="stats">
            <button className={`stat ${!filters.status && !filters.assigned ? 'active' : ''}`} onClick={() => { setFilter('assigned', ''); setFilter('status', '') }}>
              <strong>{summary.open}</strong> open
            </button>
            <button className={`stat ${filters.assigned === 'me' ? 'active' : ''}`} onClick={() => setFilter('assigned', 'me')}>
              <strong>{summary.mine}</strong> mine
            </button>
            <button className={`stat ${filters.assigned === 'unassigned' ? 'active' : ''}`} onClick={() => setFilter('assigned', 'unassigned')}>
              <strong>{summary.unassigned}</strong> unassigned
            </button>
            <span className="stat"><strong>{summary.docs_pending_review}</strong> docs to review</span>
          </div>
        )}
      </div>

      <div className="card filters">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            setFilter('q', q)
          }}
        >
          <input placeholder="Search address, postal code, homeowner…" value={q} onChange={(e) => setQ(e.target.value)} />
          <button type="submit">Search</button>
        </form>
        <select value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
          <option value="">Open statuses</option>
          <option value="all">All statuses</option>
          {options?.statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select value={filters.assigned} onChange={(e) => setFilter('assigned', e.target.value)}>
          <option value="">Anyone</option>
          <option value="me">Assigned to me</option>
          <option value="unassigned">Unassigned</option>
        </select>
        <select value={filters.suite_type} onChange={(e) => setFilter('suite_type', e.target.value)}>
          <option value="">Both paths</option>
          <option value="new">New suite</option>
          <option value="legalize_existing">Legalize existing</option>
        </select>
        <select value={filters.ordering} onChange={(e) => setFilter('ordering', e.target.value)}>
          <option value="-created_at">Newest first</option>
          <option value="created_at">Oldest first</option>
          <option value="-updated_at">Recently updated</option>
          <option value="status">By status</option>
        </select>
      </div>

      {error && <p className="bad">{error}</p>}
      {!page && !error && <p className="muted">Loading…</p>}

      {page && (
        <div className="card">
          {page.results.length === 0 && <p className="muted">No applications match these filters.</p>}
          {page.results.length > 0 && (
            <table className="table queue">
              <thead>
                <tr>
                  <th>Property</th>
                  <th>Homeowner</th>
                  <th>Path</th>
                  <th>Status</th>
                  <th>Assigned</th>
                  <th>Docs</th>
                  <th>Submitted</th>
                </tr>
              </thead>
              <tbody>
                {page.results.map((a) => (
                  <tr key={a.id}>
                    <td><Link to={`/ops/applications/${a.id}`}><strong>{a.street_address}</strong></Link><div className="muted">{a.postal_code}</div></td>
                    <td>{a.homeowner.name}<div className="muted">{a.homeowner.email}</div></td>
                    <td>{a.suite_type === 'new' ? 'New' : 'Legalize'}{a.pursuing_incentive && <div className="muted">incentive</div>}</td>
                    <td><StatusPill status={a.status} label={a.status_display} /></td>
                    <td>{a.assigned_staff ? a.assigned_staff.name : <span className="muted">—</span>}</td>
                    <td>
                      {a.docs_uploaded}/{a.docs_required}
                      {a.docs_pending_review > 0 && <div className="pill pill-doc-uploaded">{a.docs_pending_review} to review</div>}
                      {a.items_needing_work > 0 && <div className="muted">{a.items_needing_work} code items</div>}
                    </td>
                    <td className="muted">{formatDate(a.submitted_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {total > pageSize && (
            <div className="pager">
              <button disabled={pageNum <= 1} onClick={() => setFilter('page', String(pageNum - 1))}>Previous</button>
              <span className="muted">Page {pageNum} of {lastPage} · {total} total</span>
              <button disabled={pageNum >= lastPage} onClick={() => setFilter('page', String(pageNum + 1))}>Next</button>
            </div>
          )}
        </div>
      )}
    </>
  )
}
