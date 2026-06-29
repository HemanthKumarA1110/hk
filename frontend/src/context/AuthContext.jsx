import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { fetchMe } from '../api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const logout = () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    setUser(null)
  }

  const bootstrap = async () => {
    const token = localStorage.getItem('access_token')
    if (!token) {
      setLoading(false)
      return
    }
    try {
      const profile = await fetchMe()
      setUser(profile)
    } catch {
      logout()
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    bootstrap()
  }, [])

  const value = useMemo(
    () => ({
      user,
      setUser,
      loading,
      logout,
      isAuthenticated: Boolean(user),
    }),
    [user, loading]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return ctx
}
