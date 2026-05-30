import { useState } from 'react'
import LoginForm from '../components/LoginForm'
import RegisterForm from '../components/RegisterForm'
import type { UserInfo } from '../types'

interface Props {
  onAuthSuccess: (user: UserInfo) => void
}

export default function AuthPage({ onAuthSuccess }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login')

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div style={{ textAlign: 'center', marginBottom: '24px' }}>
          <div className="brand-mark" style={{ width: '56px', height: '56px', margin: '0 auto 16px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '24px', fontWeight: 800, color: 'var(--accent)' }}>
            R
          </div>
          <h1 className="auth-title">RAG News</h1>
          <p className="auth-subtitle">AI-powered news intelligence</p>
        </div>
        {mode === 'login' ? (
          <LoginForm
            onSwitchToRegister={() => setMode('register')}
            onLoginSuccess={onAuthSuccess}
          />
        ) : (
          <RegisterForm
            onSwitchToLogin={() => setMode('login')}
            onRegisterSuccess={onAuthSuccess}
          />
        )}
      </div>
    </div>
  )
}
