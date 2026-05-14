import { useState } from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import AuthPage from './pages/AuthPage'
import ChatWindow from './components/ChatWindow'
import SourcePanel from './components/SourcePanel'
import HealthBadge from './components/HealthBadge'
import IngestPanel from './components/IngestPanel'
import { HistoryPanel } from './components/HistoryPanel'
import { Dashboard } from './components/Dashboard'

function AppContent() {
  const { isAuthenticated, login, logout, user } = useAuth()
  const [sources, setSources] = useState<any[]>([])
  const [panelCollapsed, setPanelCollapsed] = useState(false)

  if (!isAuthenticated) {
    return <AuthPage onAuthSuccess={login} />
  }

  return (
    <div className="flex h-screen">
      {/* Chat Area - 70% */}
      <div className="flex-1 flex flex-col">
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-900">RAG News Intelligence</h1>
          <div className="flex items-center gap-4">
            <Dashboard />
            <HealthBadge />
            <div className="flex items-center gap-3 ml-4">
              <span className="text-sm text-gray-600">{user?.email}</span>
              <button onClick={logout} className="text-sm text-blue-600 hover:underline">
                退出
              </button>
            </div>
          </div>
        </header>
        <ChatWindow onSourcesUpdate={setSources} />
      </div>

      {/* Source Panel - 30% */}
      <div className={`border-l border-gray-200 bg-white transition-all duration-300 ${panelCollapsed ? 'w-12' : 'w-96'}`}>
        <button
          onClick={() => setPanelCollapsed(!panelCollapsed)}
          className="w-full px-4 py-3 border-b border-gray-200 text-left text-sm font-medium text-gray-700 hover:bg-gray-50 flex items-center justify-between"
        >
          <span>{panelCollapsed ? '→' : '←'} Sources ({sources.length})</span>
        </button>
        {!panelCollapsed && (
          <>
            <div className="p-4 border-b border-gray-200">
              <HistoryPanel />
            </div>
            <IngestPanel />
            <SourcePanel sources={sources} />
          </>
        )}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}