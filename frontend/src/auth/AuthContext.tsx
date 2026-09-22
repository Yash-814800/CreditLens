import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, registerUnauthorizedHandler, tokenStore } from '../api/client'
import type { Role } from '../api/types'

interface AuthState {
  role: Role | null
  email: string | null
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const [role, setRole] = useState<Role | null>(() => tokenStore.getRole() as Role | null)
  const [email, setEmail] = useState<string | null>(null)

  useEffect(() => {
    registerUnauthorizedHandler(() => {
      setRole(null)
      setEmail(null)
      navigate('/login', { replace: true })
    })
  }, [navigate])

  useEffect(() => {
    if (tokenStore.get() && !email) {
      api
        .me()
        .then((me) => setEmail(me.email))
        .catch(() => {
          /* token invalid; the 401 handler above already redirects */
        })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      role,
      email,
      isAuthenticated: role !== null,
      login: async (loginEmail: string, password: string) => {
        const res = await api.login({ email: loginEmail, password })
        tokenStore.set(res.access_token, res.role)
        setRole(res.role as Role)
        setEmail(loginEmail)
      },
      logout: () => {
        tokenStore.clear()
        setRole(null)
        setEmail(null)
        navigate('/login', { replace: true })
      },
    }),
    [role, email, navigate],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
