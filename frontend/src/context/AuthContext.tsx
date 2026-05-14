import { createContext, useContext, useState, ReactNode } from 'react'
import type { UserInfo } from '../types'
import { getStoredUser, logout as apiLogout } from '../api/client'

interface AuthContextType {
  user: UserInfo | null
  isAuthenticated: boolean
  login: (user: UserInfo) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(() => getStoredUser())

  const isAuthenticated = user !== null

  const login = (userInfo: UserInfo) => {
    setUser(userInfo)
  }

  const logout = () => {
    apiLogout()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, isAuthenticated, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}