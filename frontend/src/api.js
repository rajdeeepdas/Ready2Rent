// Single HTTP client for the SPA.
//
// Security model (Gate 3):
//   - The access token lives ONLY in this module's memory (never localStorage/sessionStorage).
//   - The refresh token is an HttpOnly cookie the browser sends to /api/auth/* automatically.
//   - Refresh and logout are CSRF-protected: we send the csrftoken cookie back as a header.
//   - All requests are same-origin (/api proxied), so `credentials: 'include'` is only needed
//     for the optional app./api. subdomain deployment; it is harmless same-origin.

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

let accessToken = null
let refreshPromise = null

export function setAccessToken(token) {
  accessToken = token
}
export function getAccessToken() {
  return accessToken
}

function readCookie(name) {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return m ? decodeURIComponent(m[1]) : null
}

export class ApiError extends Error {
  constructor(status, body) {
    super(bodyMessage(body) || `Request failed (${status})`)
    this.status = status
    this.body = body
  }
}

function bodyMessage(body) {
  if (!body) return null
  if (typeof body.detail === 'string') return body.detail
  // DRF field errors: { field: ["msg"] } or nested { property: { postal_code: ["msg"] } }
  const first = Object.entries(body)[0]
  if (first) {
    const [field, msgs] = first
    if (msgs && typeof msgs === 'object' && !Array.isArray(msgs)) {
      const inner = bodyMessage(msgs)
      return inner ? `${field} → ${inner}` : field
    }
    const msg = Array.isArray(msgs) ? msgs[0] : msgs
    return field === 'non_field_errors' ? String(msg) : `${field}: ${msg}`
  }
  return null
}

async function rawFetch(path, { method = 'GET', body, form, auth = true, csrf = false, raw = false } = {}) {
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`
  if (csrf) {
    const token = readCookie('csrftoken')
    if (token) headers['X-CSRFToken'] = token
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    credentials: 'include',
    body: form !== undefined ? form : body === undefined ? undefined : JSON.stringify(body),
  })
  if (raw) return { res, data: null }
  const data = res.status === 204 ? null : await res.json().catch(() => null)
  return { res, data }
}

/** Ensure the csrftoken cookie exists (needed before refresh/logout on a cold load). */
export async function ensureCsrf() {
  if (!readCookie('csrftoken')) await rawFetch('/api/auth/csrf/', { auth: false })
}

/** Exchange the refresh cookie for a new access token. Returns the user or null. */
export async function refreshSession() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      await ensureCsrf()
      const { res, data } = await rawFetch('/api/auth/refresh/', { method: 'POST', auth: false, csrf: true })
      if (!res.ok) {
        accessToken = null
        return null
      }
      accessToken = data.access
      return data.user
    })().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

/**
 * Authenticated request. On a 401 (expired access token) it refreshes once and retries.
 * Pass `form` (a FormData) for multipart uploads, `body` for JSON.
 */
export async function api(path, options = {}) {
  let { res, data } = await rawFetch(path, options)
  if (res.status === 401 && options.auth !== false) {
    const user = await refreshSession()
    if (user) ({ res, data } = await rawFetch(path, options))
  }
  if (!res.ok) {
    if (options.raw) data = await res.json().catch(() => null)
    throw new ApiError(res.status, data)
  }
  return options.raw ? res : data
}

/** Download a protected file: fetch with the bearer token and hand the browser a blob. */
export async function downloadFile(path, filename) {
  const res = await api(path, { raw: true })
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'document'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

// ---- Auth endpoints ----------------------------------------------------------
// Login and register also carry the CSRF token: the API rejects them otherwise, which blocks
// "login CSRF" (a hostile page signing the victim into an attacker-controlled account).
export async function login(email, password) {
  await ensureCsrf()
  const { res, data } = await rawFetch('/api/auth/login/', {
    method: 'POST',
    body: { email, password },
    auth: false,
    csrf: true,
  })
  if (!res.ok) throw new ApiError(res.status, data)
  accessToken = data.access
  return data.user
}

export async function register(fields) {
  await ensureCsrf()
  const { res, data } = await rawFetch('/api/auth/register/', { method: 'POST', body: fields, auth: false, csrf: true })
  if (!res.ok) throw new ApiError(res.status, data)
  accessToken = data.access
  return data.user
}

export async function logout() {
  try {
    await ensureCsrf()
    await rawFetch('/api/auth/logout/', { method: 'POST', auth: false, csrf: true })
  } finally {
    accessToken = null
  }
}

export const getMe = () => api('/api/auth/me/')
export const getHealth = () => api('/api/health/') // staff/admin only; sends the bearer token

// ---- Ops endpoints -----------------------------------------------------------
const qs = (params) => {
  const s = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') s.set(k, v)
  })
  const str = s.toString()
  return str ? `?${str}` : ''
}

export const ops = {
  options: () => api('/api/ops/options/'),
  staff: () => api('/api/ops/staff/'),
  queue: (params) => api(`/api/ops/applications/${qs(params)}`),
  summary: () => api('/api/ops/applications/summary/'),
  getApplication: (id) => api(`/api/ops/applications/${id}/`),
  patchApplication: (id, body) => api(`/api/ops/applications/${id}/`, { method: 'PATCH', body }),
  transition: (id, to_status, note) => api(`/api/ops/applications/${id}/transition/`, { method: 'POST', body: { to_status, note } }),
  claim: (id) => api(`/api/ops/applications/${id}/claim/`, { method: 'POST', body: {} }),
  assign: (id, staff_id, note) => api(`/api/ops/applications/${id}/assign/`, { method: 'POST', body: { staff_id, note } }),
  addNote: (id, note) => api(`/api/ops/applications/${id}/notes/`, { method: 'POST', body: { note } }),
  editCompliance: (id, itemId, body) => api(`/api/ops/applications/${id}/compliance/${itemId}/`, { method: 'PATCH', body }),
  addCompliance: (id, body) => api(`/api/ops/applications/${id}/compliance/`, { method: 'POST', body }),
  addPermit: (id, body) => api(`/api/ops/applications/${id}/permits/`, { method: 'POST', body }),
  editPermit: (id, permitId, body) => api(`/api/ops/applications/${id}/permits/${permitId}/`, { method: 'PATCH', body }),
  addVisit: (id, body) => api(`/api/ops/applications/${id}/visits/`, { method: 'POST', body }),
  editVisit: (id, visitId, body) => api(`/api/ops/applications/${id}/visits/${visitId}/`, { method: 'PATCH', body }),
  reviewDocuments: (id, decisions) => api(`/api/ops/applications/${id}/documents/review/`, { method: 'POST', body: { decisions } }),
}

// ---- Homeowner endpoints -----------------------------------------------------
export const homeowner = {
  intakeOptions: () => api('/api/homeowner/intake-options/'),
  listApplications: () => api('/api/homeowner/applications/'),
  submitIntake: (payload) => api('/api/homeowner/applications/', { method: 'POST', body: payload }),
  getApplication: (id) => api(`/api/homeowner/applications/${id}/`),
  withdraw: (id, note) => api(`/api/homeowner/applications/${id}/withdraw/`, { method: 'POST', body: { note } }),
  uploadDocument: (appId, docId, file) => {
    const form = new FormData()
    form.append('file', file)
    return api(`/api/homeowner/applications/${appId}/documents/${docId}/upload/`, { method: 'POST', form })
  },
  addOtherDocument: (appId, file, notes) => {
    const form = new FormData()
    form.append('file', file)
    form.append('notes', notes || '')
    return api(`/api/homeowner/applications/${appId}/documents/`, { method: 'POST', form })
  },
}
