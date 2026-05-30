import { useState, FormEvent } from 'react'
import { register as registerApi } from '../api/client'
import type { RegisterRequest } from '../types'

interface Props {
  onSwitchToLogin: () => void
  onRegisterSuccess: (user: any) => void
}

export default function RegisterForm({ onSwitchToLogin, onRegisterSuccess }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const req: RegisterRequest = { email, password }
      if (companyName) req.company_name = companyName
      const res = await registerApi(req)
      onRegisterSuccess(res.user)
    } catch (err: any) {
      setError(err.message || 'Registration failed')
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
        <label htmlFor="reg-email">Email</label>
        <input
          id="reg-email"
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          required
          placeholder="your@email.com"
        />
      </div>
      <div className="auth-field">
        <label htmlFor="reg-password">Password</label>
        <input
          id="reg-password"
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          required
          minLength={8}
          placeholder="Min. 8 characters"
        />
      </div>
      <div className="auth-field">
        <label htmlFor="reg-company">Company <span style={{ color: 'var(--faint)' }}>(optional)</span></label>
        <input
          id="reg-company"
          type="text"
          value={companyName}
          onChange={e => setCompanyName(e.target.value)}
          placeholder="Auto-generated if blank"
        />
      </div>
      <button type="submit" disabled={loading} className="auth-submit">
        {loading ? 'Creating account...' : 'Create account'}
      </button>
      <p className="auth-switch">
        Already have an account? <button type="button" onClick={onSwitchToLogin}>Sign in</button>
      </p>
    </form>
  )
}
