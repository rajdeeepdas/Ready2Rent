import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { downloadFile, homeowner } from '../api.js'
import { StageTimeline, StatusPill, formatDate, formatDateTime } from '../components/status.jsx'

const ACCEPT = '.pdf,.png,.jpg,.jpeg'

function DocumentRow({ appId, doc, onChange }) {
  const input = useRef(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const locked = doc.status === 'accepted'

  async function onFile(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      await homeowner.uploadDocument(appId, doc.id, file)
      await onChange()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <tr>
      <td>
        <strong>{doc.doc_type_display}</strong>
        {doc.notes && <div className="muted">{doc.notes}</div>}
        {error && <div className="bad">{error}</div>}
      </td>
      <td><StatusPill status={`doc-${doc.status}`} label={doc.status_display} /></td>
      <td className="muted">
        {doc.file_name ? (
          <button className="linklike" onClick={() => downloadFile(doc.download_url, doc.file_name)}>{doc.file_name}</button>
        ) : '—'}
        {doc.uploaded_at && <div>{formatDateTime(doc.uploaded_at)}</div>}
      </td>
      <td className="right">
        {!locked && (
          <>
            <input ref={input} type="file" accept={ACCEPT} onChange={onFile} hidden />
            <button onClick={() => input.current?.click()} disabled={busy}>
              {busy ? 'Uploading…' : doc.file_name ? 'Replace' : 'Upload'}
            </button>
          </>
        )}
        {locked && <span className="muted">Accepted</span>}
      </td>
    </tr>
  )
}

function AddOtherDocument({ appId, onChange }) {
  const [file, setFile] = useState(null)
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function submit(e) {
    e.preventDefault()
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      await homeowner.addOtherDocument(appId, file, notes)
      setFile(null)
      setNotes('')
      e.target.reset()
      await onChange()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="inline-form" onSubmit={submit}>
      <input type="file" accept={ACCEPT} onChange={(e) => setFile(e.target.files?.[0] || null)} />
      <input placeholder="What is this? (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <button type="submit" disabled={!file || busy}>{busy ? 'Adding…' : 'Add other document'}</button>
      {error && <span className="bad">{error}</span>}
    </form>
  )
}

export default function ApplicationDetail() {
  const { id } = useParams()
  const [app, setApp] = useState(null)
  const [error, setError] = useState(null)
  const [withdrawing, setWithdrawing] = useState(false)

  const load = useCallback(async () => {
    try {
      setApp(await homeowner.getApplication(id))
    } catch (e) {
      setError(e.status === 404 ? 'Application not found.' : e.message)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  async function withdraw() {
    const note = window.prompt('Withdraw this application? Optionally tell us why:')
    if (note === null) return
    setWithdrawing(true)
    try {
      setApp(await homeowner.withdraw(id, note))
    } catch (e) {
      setError(e.message)
    } finally {
      setWithdrawing(false)
    }
  }

  if (error) return <p className="bad">{error} <Link to="/app">Back</Link></p>
  if (!app) return <p className="muted">Loading…</p>

  const required = app.documents.filter((d) => d.doc_type !== 'other')
  const extras = app.documents.filter((d) => d.doc_type === 'other')
  const uploaded = required.filter((d) => d.file_name).length

  return (
    <>
      <p><Link to="/app" className="muted">← All applications</Link></p>
      <div className="page-head">
        <div>
          <h1>{app.property.street_address}</h1>
          <p className="muted">
            {app.suite.suite_type_display} · {app.property.city}, {app.property.province} {app.property.postal_code}
            {app.property.year_built ? ` · built ${app.property.year_built}` : ''} · submitted {formatDate(app.submitted_at)}
          </p>
        </div>
        <StatusPill status={app.status} label={app.status_display} />
      </div>

      <div className="card">
        <h2>Progress</h2>
        <StageTimeline status={app.status} />
      </div>

      <div className="card">
        <div className="card-row">
          <h2>Documents <span className="muted">({uploaded}/{required.length} uploaded)</span></h2>
          <span className="muted">PDF, PNG or JPG · max 20 MB</span>
        </div>
        <table className="table">
          <tbody>
            {required.map((d) => <DocumentRow key={d.id} appId={app.id} doc={d} onChange={load} />)}
            {extras.map((d) => <DocumentRow key={d.id} appId={app.id} doc={d} onChange={load} />)}
          </tbody>
        </table>
        {app.status !== 'withdrawn' && <AddOtherDocument appId={app.id} onChange={load} />}
      </div>

      <div className="card">
        <h2>Code checklist</h2>
        <table className="table">
          <tbody>
            {app.compliance_items.map((c) => (
              <tr key={c.id}>
                <td>{c.item_type_display}{c.notes && <div className="muted">{c.notes}</div>}</td>
                <td className="right"><StatusPill status={`ci-${c.status}`} label={c.status_display} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(app.permits.length > 0 || app.visits.length > 0) && (
        <div className="card">
          <h2>Permits & visits</h2>
          {app.permits.map((p) => (
            <div className="status" key={p.id}><span>{p.permit_type_display}{p.permit_number ? ` · #${p.permit_number}` : ''}</span><span>{p.status_display}</span></div>
          ))}
          {app.visits.map((v) => (
            <div className="status" key={v.id}><span>{v.visit_type_display} · {formatDateTime(v.scheduled_for)}</span><span>{v.status_display}</span></div>
          ))}
        </div>
      )}

      <div className="card">
        <h2>History</h2>
        <ul className="history">
          {[...app.status_history].reverse().map((h) => (
            <li key={h.id}>
              <span className="muted">{formatDateTime(h.created_at)}</span>
              <span>
                {h.from_status ? `${h.from_status} → ${h.to_status}` : `Created (${h.to_status})`}
                <span className="muted"> · by {h.changed_by_role === 'you' ? 'you' : 'Ready2Rent'}</span>
              </span>
              {h.note && <span className="note">{h.note}</span>}
            </li>
          ))}
        </ul>
      </div>

      {app.can_withdraw && (
        <p className="muted">
          Changed your mind? <button className="linklike danger" onClick={withdraw} disabled={withdrawing}>Withdraw this application</button>
        </p>
      )}
    </>
  )
}
