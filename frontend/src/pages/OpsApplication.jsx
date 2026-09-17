import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { downloadFile, ops } from '../api.js'
import { useAuth } from '../auth.jsx'
import { StageTimeline, StatusPill, formatDate, formatDateTime } from '../components/status.jsx'

function useAction(reload) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const run = async (fn) => {
    setBusy(true)
    setError(null)
    try {
      const result = await fn()
      await reload()
      return result
    } catch (e) {
      setError(e.message)
      return null
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, run, setError }
}

const labelOf = (list, value) => list?.find((o) => o.value === value)?.label || value

// ---------------------------------------------------------------------------
function AssignmentCard({ app, staff, reload }) {
  const { user } = useAuth()
  const { busy, error, run } = useAction(reload)
  const [pick, setPick] = useState(app.assigned_staff?.id || '')
  const isAdmin = user.role === 'admin'

  return (
    <div className="card">
      <h2>Assignment</h2>
      <p>
        {app.assigned_staff ? (
          <>Assigned to <strong>{app.assigned_staff.name}</strong>{app.assigned_staff.id === user.id && ' (you)'}</>
        ) : (
          <span className="muted">Unassigned</span>
        )}
      </p>
      {!app.assigned_staff && (
        <button className="primary" disabled={busy} onClick={() => run(() => ops.claim(app.id))}>Claim this lead</button>
      )}
      {isAdmin && (
        <div className="inline-form">
          <select value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">— Unassigned —</option>
            {staff.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.role})</option>)}
          </select>
          <button disabled={busy} onClick={() => run(() => ops.assign(app.id, pick || null, ''))}>Assign</button>
        </div>
      )}
      {!isAdmin && app.assigned_staff && app.assigned_staff.id !== user.id && (
        <p className="muted">Only an admin can reassign. You can read this application but not act on it.</p>
      )}
      {error && <p className="bad">{error}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
function StatusCard({ app, options, reload }) {
  const { busy, error, run } = useAction(reload)
  const [note, setNote] = useState('')

  return (
    <div className="card">
      <div className="card-row">
        <h2>Status</h2>
        <StatusPill status={app.status} label={app.status_display} />
      </div>
      <StageTimeline status={app.status} />
      {app.can_act && app.allowed_transitions.length > 0 && (
        <div className="transition-box">
          <label>
            Note for this change (optional)
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why / what happened" />
          </label>
          <div className="btn-row">
            {app.allowed_transitions.map((t) => (
              <button
                key={t}
                disabled={busy}
                className={t === 'withdrawn' ? 'danger' : t === 'on_hold' ? '' : 'primary'}
                onClick={() => run(() => ops.transition(app.id, t, note)).then((r) => r && setNote(''))}
              >
                → {labelOf(options.statuses, t)}
              </button>
            ))}
          </div>
        </div>
      )}
      {!app.can_act && <p className="muted">Claim or be assigned this application to change its status.</p>}
      {(app.status === 'inspections' || app.status === 'registered') && app.completion_blockers.length > 0 && (
        <div className="hint">
          <strong>Before this can be registered:</strong>
          <ul>{app.completion_blockers.map((b) => <li key={b}>{b}</li>)}</ul>
        </div>
      )}
      {error && <p className="bad">{error}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
function DetailsCard({ app, reload }) {
  const { busy, error, run } = useAction(reload)
  const [form, setForm] = useState({
    estimated_cost: app.estimated_cost ?? '',
    pursuing_incentive: app.pursuing_incentive,
    land_use_district: app.property.land_use_district ?? '',
  })
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  return (
    <div className="card">
      <h2>Homeowner & property</h2>
      <dl className="review">
        <dt>Homeowner</dt>
        <dd>{app.homeowner.name} · <a href={`mailto:${app.homeowner.email}`}>{app.homeowner.email}</a>{app.homeowner.phone && ` · ${app.homeowner.phone}`}</dd>
        <dt>Property</dt>
        <dd>{app.property.street_address}, {app.property.city} {app.property.postal_code}{app.property.year_built && ` · built ${app.property.year_built}`}</dd>
        <dt>Suite</dt>
        <dd>{app.suite.suite_type_display}{app.suite.has_separate_entrance !== null && ` · separate entrance: ${app.suite.has_separate_entrance ? 'yes' : 'no'}`}{app.suite.description && <div className="muted">{app.suite.description}</div>}</dd>
        <dt>Submitted</dt>
        <dd>{formatDateTime(app.submitted_at)}</dd>
      </dl>
      {app.can_act && (
        <form
          className="edit-grid"
          onSubmit={(e) => {
            e.preventDefault()
            run(() => ops.patchApplication(app.id, { ...form, estimated_cost: form.estimated_cost === '' ? null : form.estimated_cost }))
          }}
        >
          <label>
            Land use district
            <input value={form.land_use_district} onChange={set('land_use_district')} placeholder="e.g. R-CG" />
          </label>
          <label>
            Estimated cost (CAD)
            <input type="number" step="0.01" min="0" value={form.estimated_cost} onChange={set('estimated_cost')} />
          </label>
          <label className="check">
            <input type="checkbox" checked={form.pursuing_incentive} onChange={set('pursuing_incentive')} /> Pursuing incentive
          </label>
          <button type="submit" disabled={busy}>Save</button>
        </form>
      )}
      {error && <p className="bad">{error}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
function DocumentsCard({ app, reload }) {
  const { busy, error, run } = useAction(reload)
  const [selected, setSelected] = useState({})
  const [rejectNote, setRejectNote] = useState('')
  const reviewable = app.documents.filter((d) => d.file_name)
  const chosen = reviewable.filter((d) => selected[d.id])

  const toggle = (id) => setSelected((s) => ({ ...s, [id]: !s[id] }))
  const decide = (status) =>
    run(() => ops.reviewDocuments(app.id, chosen.map((d) => ({ document_id: d.id, status, notes: status === 'rejected' ? rejectNote : '' })))).then((r) => {
      if (r) {
        setSelected({})
        setRejectNote('')
      }
    })

  return (
    <div className="card">
      <div className="card-row">
        <h2>Documents</h2>
        <span className="muted">{reviewable.filter((d) => d.status === 'uploaded').length} awaiting review</span>
      </div>
      <table className="table">
        <tbody>
          {app.documents.map((d) => (
            <tr key={d.id}>
              {app.can_act && <td className="narrow"><input type="checkbox" disabled={!d.file_name} checked={!!selected[d.id]} onChange={() => toggle(d.id)} /></td>}
              <td><strong>{d.doc_type_display}</strong>{d.notes && <div className="muted">{d.notes}</div>}</td>
              <td><StatusPill status={`doc-${d.status}`} label={d.status_display} /></td>
              <td className="muted">
                {d.file_name ? <button className="linklike" onClick={() => downloadFile(d.download_url, d.file_name)}>{d.file_name}</button> : '—'}
                {d.uploaded_at && <div>{formatDateTime(d.uploaded_at)}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {app.can_act && (
        <div className="inline-form">
          <button className="primary" disabled={busy || chosen.length === 0} onClick={() => decide('accepted')}>Accept selected ({chosen.length})</button>
          <input placeholder="Rejection note for the homeowner (required to reject)" value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} />
          <button className="danger" disabled={busy || chosen.length === 0 || !rejectNote.trim()} onClick={() => decide('rejected')}>Reject selected</button>
        </div>
      )}
      {error && <p className="bad">{error}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
function ComplianceCard({ app, options, reload }) {
  const { busy, error, run } = useAction(reload)
  const [other, setOther] = useState('')

  return (
    <div className="card">
      <h2>Code checklist</h2>
      <table className="table">
        <tbody>
          {app.compliance_items.map((c) => (
            <ComplianceRow key={c.id} app={app} item={c} options={options} run={run} busy={busy} />
          ))}
        </tbody>
      </table>
      {app.can_act && (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault()
            run(() => ops.addCompliance(app.id, { notes: other, status: 'needs_work' })).then((r) => r && setOther(''))
          }}
        >
          <input placeholder="Add another code item (describe it)" value={other} onChange={(e) => setOther(e.target.value)} />
          <button type="submit" disabled={busy || !other.trim()}>Add item</button>
        </form>
      )}
      {error && <p className="bad">{error}</p>}
    </div>
  )
}

function ComplianceRow({ app, item, options, run, busy }) {
  const [notes, setNotes] = useState(item.notes)
  const dirty = notes !== item.notes
  return (
    <tr>
      <td>
        <strong>{item.item_type_display}</strong>
        {app.can_act ? (
          <div className="inline-form">
            <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" />
            {dirty && <button disabled={busy} onClick={() => run(() => ops.editCompliance(app.id, item.id, { notes }))}>Save note</button>}
          </div>
        ) : (
          item.notes && <div className="muted">{item.notes}</div>
        )}
      </td>
      <td className="right">
        {app.can_act ? (
          <select value={item.status} disabled={busy} onChange={(e) => run(() => ops.editCompliance(app.id, item.id, { status: e.target.value }))}>
            {options.compliance_statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        ) : (
          <StatusPill status={`ci-${item.status}`} label={item.status_display} />
        )}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
function PermitsCard({ app, options, reload }) {
  const { busy, error, run } = useAction(reload)
  const existing = new Set(app.permits.map((p) => p.permit_type))
  const [form, setForm] = useState({ permit_type: '', status: 'not_started', permit_number: '', applied_date: '', approved_date: '', notes: '' })
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const clean = (f) => ({ ...f, applied_date: f.applied_date || null, approved_date: f.approved_date || null, permit_number: f.permit_number || null })

  return (
    <div className="card">
      <h2>Permits</h2>
      {app.permits.length === 0 && <p className="muted">No permits recorded yet.</p>}
      <table className="table">
        <tbody>
          {app.permits.map((p) => <PermitRow key={p.id} app={app} permit={p} options={options} run={run} busy={busy} />)}
        </tbody>
      </table>
      {app.can_act && (
        <form
          className="edit-grid"
          onSubmit={(e) => {
            e.preventDefault()
            run(() => ops.addPermit(app.id, clean(form))).then((r) => r && setForm({ permit_type: '', status: 'not_started', permit_number: '', applied_date: '', approved_date: '', notes: '' }))
          }}
        >
          <label>
            Add permit
            <select value={form.permit_type} onChange={set('permit_type')} required>
              <option value="">Choose type…</option>
              {options.permit_types.filter((t) => !existing.has(t.value)).map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </label>
          <label>
            Status
            <select value={form.status} onChange={set('status')}>
              {options.permit_statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </label>
          <label>Permit #<input value={form.permit_number} onChange={set('permit_number')} /></label>
          <label>Applied<input type="date" value={form.applied_date} onChange={set('applied_date')} /></label>
          <label>Approved<input type="date" value={form.approved_date} onChange={set('approved_date')} /></label>
          <button type="submit" disabled={busy || !form.permit_type}>Add</button>
        </form>
      )}
      {error && <p className="bad">{error}</p>}
    </div>
  )
}

function PermitRow({ app, permit, options, run, busy }) {
  const [form, setForm] = useState({ status: permit.status, permit_number: permit.permit_number || '', applied_date: permit.applied_date || '', approved_date: permit.approved_date || '' })
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const dirty = form.status !== permit.status || form.permit_number !== (permit.permit_number || '') || form.applied_date !== (permit.applied_date || '') || form.approved_date !== (permit.approved_date || '')
  if (!app.can_act) {
    return (
      <tr>
        <td><strong>{permit.permit_type_display}</strong>{permit.permit_number && <div className="muted">#{permit.permit_number}</div>}</td>
        <td>{permit.status_display}</td>
        <td className="muted">{permit.applied_date && `applied ${permit.applied_date}`}{permit.approved_date && ` · approved ${permit.approved_date}`}</td>
      </tr>
    )
  }
  return (
    <tr>
      <td><strong>{permit.permit_type_display}</strong></td>
      <td>
        <select value={form.status} onChange={set('status')}>
          {options.permit_statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </td>
      <td><input placeholder="Permit #" value={form.permit_number} onChange={set('permit_number')} /></td>
      <td><input type="date" value={form.applied_date} onChange={set('applied_date')} /></td>
      <td><input type="date" value={form.approved_date} onChange={set('approved_date')} /></td>
      <td className="right">
        {dirty && (
          <button disabled={busy} onClick={() => run(() => ops.editPermit(app.id, permit.id, { ...form, permit_number: form.permit_number || null, applied_date: form.applied_date || null, approved_date: form.approved_date || null }))}>
            Save
          </button>
        )}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
function VisitsCard({ app, options, staff, reload }) {
  const { busy, error, run } = useAction(reload)
  const [form, setForm] = useState({ visit_type: 'site_assessment', scheduled_for: '', assigned_staff_id: '' })
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div className="card">
      <h2>Visits & inspections</h2>
      {app.visits.length === 0 && <p className="muted">Nothing scheduled.</p>}
      <table className="table">
        <tbody>
          {app.visits.map((v) => (
            <tr key={v.id}>
              <td><strong>{v.visit_type_display}</strong><div className="muted">{formatDateTime(v.scheduled_for)} · {v.assigned_staff ? v.assigned_staff.name : 'unassigned'}</div>{v.outcome_notes && <div className="muted">{v.outcome_notes}</div>}</td>
              <td className="right">
                {app.can_act ? (
                  <select value={v.status} disabled={busy} onChange={(e) => {
                    const status = e.target.value
                    const outcome_notes = status === 'completed' ? window.prompt('Outcome notes (optional):', v.outcome_notes || '') ?? v.outcome_notes : v.outcome_notes
                    run(() => ops.editVisit(app.id, v.id, { status, outcome_notes }))
                  }}>
                    {options.visit_statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                ) : v.status_display}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {app.can_act && (
        <form
          className="edit-grid"
          onSubmit={(e) => {
            e.preventDefault()
            run(() => ops.addVisit(app.id, { visit_type: form.visit_type, scheduled_for: new Date(form.scheduled_for).toISOString(), ...(form.assigned_staff_id ? { assigned_staff_id: form.assigned_staff_id } : {}) }))
              .then((r) => r && setForm({ visit_type: 'site_assessment', scheduled_for: '', assigned_staff_id: '' }))
          }}
        >
          <label>
            Schedule
            <select value={form.visit_type} onChange={set('visit_type')}>
              {options.visit_types.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </label>
          <label>When<input type="datetime-local" value={form.scheduled_for} onChange={set('scheduled_for')} required /></label>
          <label>
            Who
            <select value={form.assigned_staff_id} onChange={set('assigned_staff_id')}>
              <option value="">Me</option>
              {staff.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <button type="submit" disabled={busy || !form.scheduled_for}>Schedule</button>
        </form>
      )}
      {error && <p className="bad">{error}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
function HistoryCard({ app, reload }) {
  const { busy, error, run } = useAction(reload)
  const [note, setNote] = useState('')
  return (
    <div className="card">
      <h2>Notes & history</h2>
      {app.can_act && (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault()
            run(() => ops.addNote(app.id, note)).then((r) => r && setNote(''))
          }}
        >
          <input placeholder="Add an internal note (not visible to the homeowner)" value={note} onChange={(e) => setNote(e.target.value)} />
          <button type="submit" disabled={busy || !note.trim()}>Add note</button>
        </form>
      )}
      {error && <p className="bad">{error}</p>}
      <ul className="history">
        {[...app.status_history].reverse().map((h) => (
          <li key={h.id}>
            <span className="muted">{formatDateTime(h.created_at)}</span>
            <span>
              {h.is_note ? <em>Note</em> : h.from_status ? `${h.from_status} → ${h.to_status}` : `Created (${h.to_status})`}
              <span className="muted"> · {h.changed_by.name} ({h.changed_by.role})</span>
            </span>
            {h.note && <span className="note">{h.note}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------
export default function OpsApplication() {
  const { id } = useParams()
  const [app, setApp] = useState(null)
  const [options, setOptions] = useState(null)
  const [staff, setStaff] = useState([])
  const [error, setError] = useState(null)

  const reload = useCallback(async () => {
    try {
      setApp(await ops.getApplication(id))
    } catch (e) {
      setError(e.status === 404 ? 'Application not found.' : e.message)
    }
  }, [id])

  useEffect(() => {
    Promise.all([ops.options(), ops.staff()]).then(([o, s]) => { setOptions(o); setStaff(s) }).catch((e) => setError(e.message))
    reload()
  }, [reload])

  if (error) return <p className="bad">{error} <Link to="/ops">Back to queue</Link></p>
  if (!app || !options) return <p className="muted">Loading…</p>

  return (
    <>
      <p><Link to="/ops" className="muted">← Lead queue</Link></p>
      <div className="page-head">
        <div>
          <h1>{app.property.street_address}</h1>
          <p className="muted">{app.homeowner.name} · {app.suite.suite_type_display} · submitted {formatDate(app.submitted_at)}</p>
        </div>
        <StatusPill status={app.status} label={app.status_display} />
      </div>
      <div className="two-col">
        <StatusCard app={app} options={options} reload={reload} />
        <AssignmentCard app={app} staff={staff} reload={reload} />
      </div>
      <DetailsCard app={app} reload={reload} />
      <DocumentsCard app={app} reload={reload} />
      <ComplianceCard app={app} options={options} reload={reload} />
      <PermitsCard app={app} options={options} reload={reload} />
      <VisitsCard app={app} options={options} staff={staff} reload={reload} />
      <HistoryCard app={app} reload={reload} />
    </>
  )
}
