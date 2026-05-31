import { useState, useCallback, useEffect } from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import AuthPage from './pages/AuthPage'
import ChatWindow from './components/ChatWindow'
import SourcePanel from './components/SourcePanel'
import HealthBadge from './components/HealthBadge'
import IngestPanel from './components/IngestPanel'
import { HistoryPanel, addToHistory } from './components/HistoryPanel'
import { Dashboard } from './components/Dashboard'
import ResearchPanel from './components/ResearchPanel'
import ErrorBoundary from './components/ErrorBoundary'
import type { Source } from './types'

function AppContent() {
  const { logout, user } = useAuth()
  const [sources, setSources] = useState<Source[]>([])
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0)
  const [externalQuery, setExternalQuery] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [mode, setMode] = useState<'research' | 'chat'>('research')

  // Close sidebar on escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setSidebarOpen(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  const handleSourcesUpdate = (newSources: Source[]) => {
    setSources(newSources)
    if (newSources.length > 0) {
      addToHistory('Query', newSources.length)
      setHistoryRefreshKey(k => k + 1)
    }
  }

  const handleQuerySelect = useCallback((query: string) => {
    setExternalQuery(query)
  }, [])

  return (
    <ErrorBoundary>
    <div className="app-shell">
      <button className="sidebar-toggle" aria-label="Toggle sidebar" onClick={() => setSidebarOpen(o => !o)}>
        <span aria-hidden="true">{sidebarOpen ? '✕' : '☰'}</span>
      </button>
      {sidebarOpen && <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} />}
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`} aria-label="侧边栏">
        <div className="sidebar-header">
          <div className="brand">
            <div className="brand-mark" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', fontWeight: 800, color: 'var(--accent)' }}>
              R
            </div>
            <div>
              <strong>RAG News</strong>
              <span>AI intelligence</span>
            </div>
          </div>
          <div className="sidebar-user">
            <span className="sidebar-user-email" title={user?.email}>{user?.email}</span>
            <button onClick={logout} className="ghost-button sidebar-logout" aria-label="退出登录">
              退出
            </button>
          </div>
        </div>

        <section className="sidebar-section conversations" aria-labelledby="conversation-title">
          <div className="section-heading">
            <h2 id="conversation-title">历史对话</h2>
          </div>
          <HistoryPanel compact onQuerySelect={handleQuerySelect} refreshKey={historyRefreshKey} />
        </section>

        <section className="sidebar-section" aria-labelledby="stats-title">
          <div className="section-heading">
            <h2 id="stats-title">数据概览</h2>
          </div>
          <Dashboard compact />
        </section>

        <section className="sidebar-section" aria-labelledby="sources-title">
          <div className="section-heading">
            <h2 id="sources-title">来源 ({sources.length})</h2>
          </div>
          <SourcePanel sources={sources} compact />
        </section>

        <section className="sidebar-section" aria-labelledby="ingest-title">
          <div className="section-heading">
            <h2 id="ingest-title">数据导入</h2>
          </div>
          <IngestPanel compact />
        </section>

      </aside>

      <main className="chat-panel">
        <header className="chat-header">
          <div>
            <p className="eyebrow">RAG-powered news intelligence</p>
            <h1>RAG News</h1>
            <p className="header-copy">Deep research or quick Q&amp;A — your call.</p>
          </div>
          <div className="header-actions">
            <HealthBadge />
          </div>
        </header>

        <div className="mode-tabs">
          <button className={`mode-tab ${mode === 'research' ? 'active' : ''}`} onClick={() => setMode('research')}>深度研究</button>
          <button className={`mode-tab ${mode === 'chat' ? 'active' : ''}`} onClick={() => setMode('chat')}>对话问答</button>
        </div>

        {mode === 'research' ? (
          <ResearchPanel />
        ) : (
          <div className="chat-content">
            <ChatWindow onSourcesUpdate={handleSourcesUpdate} externalQuery={externalQuery} onExternalQueryConsumed={() => setExternalQuery('')} />
          </div>
        )}
      </main>
    </div>
    </ErrorBoundary>
  )
}

function AppLoader() {
  const { isAuthenticated, login } = useAuth()

  if (!isAuthenticated) {
    return <AuthPage onAuthSuccess={login} />
  }

  return <AppContent />
}

export default function App() {
  return (
    <AuthProvider>
      <AppLoader />
    </AuthProvider>
  )
}
