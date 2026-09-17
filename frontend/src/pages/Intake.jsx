import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { homeowner } from '../api.js'

const STEPS = ['Property', 'Suite', 'Code items', 'Goals & review']

const initial = {
  property: { street_address: '', city: 'Calgary', province: 'AB', postal_code: '', year_built: '' },
  suite: { suite_type: '', has_separate_entrance: '', description: '' },
  compliance: {},
  other_issues: '',
  goals: { pursuing_incentive: false, wants_financing_guidance: false, notes: '' },
}

export default function Intake() {
  const navigate = useNavigate()
  const [options, setOptions] = useState(null)
  const [step, setStep] = useState(0)
  const [form, setForm] = useState(initial)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    homeowner.intakeOptions().then(setOptions).catch((e) => setError(e.message))
  }, [])

  const setSection = (section, key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => ({ ...f, [section]: { ...f[section], [key]: value } }))
  }
  const setCompliance = (item, value) => setForm((f) => ({ ...f, compliance: { ...f.compliance, [item]: value } }))

  function validateStep() {
    if (step === 0) {
      if (!form.property.street_address.trim()) return 'Street address is required.'
      if (!form.property.postal_code.trim()) return 'Postal code is required.'
      const y = form.property.year_built
      if (y !== '' && (Number(y) < 1800 || Number(y) > 2100)) return 'Year built looks wrong.'
    }
    if (step === 1 && !form.suite.suite_type) return 'Choose which path applies to you.'
    return null
  }

  function next() {
    const problem = validateStep()
    if (problem) return setError(problem)
    setError(null)
    setStep((s) => s + 1)
  }

  function toPayload() {
    const yb = form.property.year_built
    const sep = form.suite.has_separate_entrance
    return {
      property: { ...form.property, year_built: yb === '' ? null : Number(yb) },
      suite: { ...form.suite, has_separate_entrance: sep === '' ? null : sep === 'yes' },
      compliance: form.compliance,
      other_issues: form.other_issues,
      goals: form.goals,
    }
  }

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const app = await homeowner.submitIntake(toPayload())
      navigate(`/app/applications/${app.id}`, { replace: true })
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (!options && !error) return <p className="muted">Loading…</p>

  const pre1990 = form.property.year_built !== '' && Number(form.property.year_built) < 1990

  return (
    <div className="card wizard">
      <div className="page-head">
        <h1>New application</h1>
        <Link to="/app" className="muted">Cancel</Link>
      </div>
      <ol className="steps">
        {STEPS.map((label, i) => (
          <li key={label} className={i === step ? 'current' : i < step ? 'done' : ''}>{label}</li>
        ))}
      </ol>

      {step === 0 && options && (
        <section>
          <h2>Where is the property?</h2>
          <label>
            Street address
            <input value={form.property.street_address} onChange={setSection('property', 'street_address')} placeholder="1234 17 Ave SW" required />
          </label>
          <div className="row">
            <label>
              City
              <input value={form.property.city} onChange={setSection('property', 'city')} />
            </label>
            <label>
              Province
              <input value={form.property.province} onChange={setSection('property', 'province')} maxLength={2} />
            </label>
            <label>
              Postal code
              <input value={form.property.postal_code} onChange={setSection('property', 'postal_code')} placeholder="T2T 0C3" required />
            </label>
          </div>
          <label>
            Year built (if known)
            <input type="number" value={form.property.year_built} onChange={setSection('property', 'year_built')} placeholder="1975" min={1800} max={2100} />
          </label>
          {pre1990 && (
            <p className="hint">Homes built before 1990 need an asbestos abatement form with the City application. We will add it to your document checklist.</p>
          )}
        </section>
      )}

      {step === 1 && options && (
        <section>
          <h2>Which path applies?</h2>
          <div className="choice-list">
            {options.suite_types.map((o) => (
              <label key={o.value} className={`choice ${form.suite.suite_type === o.value ? 'selected' : ''}`}>
                <input type="radio" name="suite_type" value={o.value} checked={form.suite.suite_type === o.value} onChange={setSection('suite', 'suite_type')} />
                <span>
                  <strong>{o.label}</strong>
                  <br />
                  <span className="muted">
                    {o.value === 'new' ? 'Designing and building a suite from scratch to current code.' : 'Bringing an already-built suite up to code and registering it.'}
                  </span>
                </span>
              </label>
            ))}
          </div>
          <label>
            Does the suite have its own separate entrance?
            <select value={form.suite.has_separate_entrance} onChange={setSection('suite', 'has_separate_entrance')}>
              <option value="">Not sure / not built yet</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </label>
          <label>
            Describe the suite (optional)
            <textarea rows={3} value={form.suite.description} onChange={setSection('suite', 'description')} placeholder="Bedrooms, bathroom, kitchen, who built it, anything a reviewer should know…" />
          </label>
        </section>
      )}

      {step === 2 && options && (
        <section>
          <h2>Known code items</h2>
          <p className="muted">These are the items the City checks most often. Answer what you know; “Not sure” is fine.</p>
          <table className="compliance-table">
            <tbody>
              {options.compliance_items.map((item) => (
                <tr key={item.value}>
                  <td>{item.label}</td>
                  <td>
                    <div className="seg">
                      {options.self_report_statuses.map((s) => (
                        <label key={s.value} className={form.compliance[item.value] === s.value ? 'selected' : ''}>
                          <input type="radio" name={item.value} value={s.value} checked={form.compliance[item.value] === s.value} onChange={() => setCompliance(item.value, s.value)} />
                          {s.label}
                        </label>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <label>
            Anything else you already know needs fixing? (optional)
            <textarea rows={2} value={form.other_issues} onChange={(e) => setForm((f) => ({ ...f, other_issues: e.target.value }))} />
          </label>
        </section>
      )}

      {step === 3 && (
        <section>
          <h2>Goals</h2>
          <label className="check">
            <input type="checkbox" checked={form.goals.pursuing_incentive} onChange={setSection('goals', 'pursuing_incentive')} />
            I am interested in the City’s Secondary Suite Incentive Program
          </label>
          <p className="hint">
            Note: as of June 2026 new applications to the incentive program are waitlisted and the program is winding down. We will tell you if
            anything changes; please don’t plan your budget around it.
          </p>
          <label className="check">
            <input type="checkbox" checked={form.goals.wants_financing_guidance} onChange={setSection('goals', 'wants_financing_guidance')} />
            I would like guidance on financing options
          </label>
          <p className="hint">We connect you with licensed lenders and explain the process. We never arrange or broker financing ourselves.</p>
          <label>
            What are you hoping to achieve, and by when? (optional)
            <textarea rows={3} value={form.goals.notes} onChange={setSection('goals', 'notes')} />
          </label>

          <h2>Review</h2>
          <dl className="review">
            <dt>Property</dt>
            <dd>{form.property.street_address}, {form.property.city} {form.property.postal_code}{form.property.year_built ? ` · built ${form.property.year_built}` : ''}</dd>
            <dt>Path</dt>
            <dd>{options?.suite_types.find((o) => o.value === form.suite.suite_type)?.label}</dd>
            <dt>Code items answered</dt>
            <dd>{Object.keys(form.compliance).length} of {options?.compliance_items.length}</dd>
          </dl>
          <p className="muted">Submitting creates your application and your personalised document checklist in one step.</p>
        </section>
      )}

      {error && <p className="bad">{error}</p>}
      <div className="wizard-nav">
        <button type="button" onClick={() => setStep((s) => s - 1)} disabled={step === 0 || busy}>Back</button>
        {step < STEPS.length - 1 ? (
          <button type="button" className="primary" onClick={next}>Continue</button>
        ) : (
          <button type="button" className="primary" onClick={submit} disabled={busy}>{busy ? 'Submitting…' : 'Submit application'}</button>
        )}
      </div>
    </div>
  )
}
