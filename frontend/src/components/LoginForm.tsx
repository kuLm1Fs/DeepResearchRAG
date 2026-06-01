import { useState, FormEvent } from 'react'
import { login as loginApi } from '../api/client'
import type { LoginRequest, UserInfo } from '../types'

interface Props {
  onSwitchToRegister: () => void
  onLoginSuccess: (user: UserInfo) => void
}

export default function LoginForm({ onSwitchToRegister, onLoginSuccess }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await loginApi({ email, password } as LoginRequest)
      onLoginSuccess(res.user)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      {error && (
        <div className="ingest-message error">{error}</div>
      )}
      <div className="auth-field">
        <label htmlFor="login-email">Email</label>
        <input
          id="login-email"
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          required
          placeholder="your@email.com"
        />
      </div>
      <div className="auth-field">
        <label htmlFor="login-password">Password</label>
        <input
          id="login-password"
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          required
          placeholder="••••••••"
        />
      </div>
      <button type="submit" disabled={loading} className="auth-submit">
        {loading ? 'Signing in...' : 'Sign in'}
      </button>
      <p className="auth-switch">
        No account? <button type="button" onClick={onSwitchToRegister}>Register</button>
      </p>
    </form>
  )
}
