// Shared status helpers for the homeowner UI.

export const STAGES = [
  ['intake', 'Intake'],
  ['eligibility_check', 'Eligibility'],
  ['development_permit', 'Development permit'],
  ['permits', 'Permits'],
  ['construction', 'Construction'],
  ['inspections', 'Inspections'],
  ['registered', 'Registered'],
  ['complete', 'Complete'],
]

export function StatusPill({ status, label }) {
  return <span className={`pill pill-status pill-${status}`}>{label || status}</span>
}

export function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-CA', { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatDateTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-CA', { dateStyle: 'medium', timeStyle: 'short' })
}

/** Horizontal progress through the main stages; on_hold / withdrawn shown as a banner. */
export function StageTimeline({ status }) {
  const idx = STAGES.findIndex(([s]) => s === status)
  const paused = status === 'on_hold' || status === 'withdrawn'
  return (
    <div>
      {paused && (
        <p className={status === 'withdrawn' ? 'banner bad-bg' : 'banner warn-bg'}>
          {status === 'withdrawn' ? 'This application has been withdrawn.' : 'This application is on hold. Our team will be in touch.'}
        </p>
      )}
      <ol className="timeline">
        {STAGES.map(([s, label], i) => {
          const cls = paused ? 'pending' : i < idx ? 'done' : i === idx ? 'current' : 'pending'
          return (
            <li key={s} className={cls}>
              <span className="dot" />
              <span className="label">{label}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
