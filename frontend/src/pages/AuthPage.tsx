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
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-md p-6 bg-white rounded-lg shadow-md">
        <div className="text-center mb-6">
          <h1 className="text-3xl font-bold text-gray-900">RAG News</h1>
          <p className="text-gray-500 text-sm mt-1">AI 行业深度研究平台</p>
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