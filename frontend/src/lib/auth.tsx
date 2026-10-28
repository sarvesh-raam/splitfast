import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, clearSession, getStoredUser, getToken, saveSession, type User } from './api'

type AuthState = {
  user: User | null
  login: (email: string, password: string) => Promise<void>
  register: (name: string, email: string, password: string) => Promise<void>
  logout: () => void
  setUpiId: (upiId: string) => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(getStoredUser)
  const qc = useQueryClient()

  useEffect(() => {
    const onLogout = () => setUser(null)
    window.addEventListener('splitfast:logout', onLogout)
    return () => window.removeEventListener('splitfast:logout', onLogout)
  }, [])

  const start = useCallback((session: { token: string; user: User }) => {
    saveSession(session.token, session.user)
    setUser(session.user)
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      login: async (email, password) => start(await api('/api/auth/login', { body: { email, password } })),
      register: async (name, email, password) =>
        start(await api('/api/auth/register', { body: { name, email, password } })),
      logout: () => {
        clearSession()
        qc.clear()
        setUser(null)
      },
      setUpiId: async (upiId) => {
        const updated = await api<User>('/api/auth/me', { method: 'PATCH', body: { upi_id: upiId } })
        saveSession(getToken() ?? '', updated)
        setUser(updated)
        qc.invalidateQueries({ queryKey: ['group'] })
      },
    }),
    [user, start, qc],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// oxlint-disable-next-line react/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}
