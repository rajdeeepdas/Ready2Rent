import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import * as apiClient from './api.js'

const AuthContext = createContext(null)

/**
 * Session state for the SPA.
 *   status: 'loading' (checking refresh cookie on page load) | 'anon' | 'authed'
 * On load we call the refresh endpoint: if the HttpOnly refresh cookie is valid we get a
 * fresh in-memory access token and the user; otherwise the user is anonymous.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    let cancelled = false
    apiClient
      .refreshSession()
      .then((u) => {
        if (cancelled) return
        setUser(u)
        setStatus(u ? 'authed' : 'anon')
      })
      .catch(() => {
        if (!cancelled) setStatus('anon')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email, password) => {
    const u = await apiClient.login(email, password)
    setUser(u)
    setStatus('authed')
    return u
  }, [])

  const register = useCallback(async (fields) => {
    const u = await apiClient.register(fields)
    setUser(u)
    setStatus('authed')
    return u
  }, [])

  const logout = useCallback(async () => {
    await apiClient.logout()
    setUser(null)
    setStatus('anon')
  }, [])

  const value = useMemo(() => ({ user, status, login, register, logout, setUser }), [user, status, login, register, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

export const isOps = (user) => user && (user.role === 'staff' || user.role === 'admin')
export const homeFor = (user) => (isOps(user) ? '/ops' : '/app')
