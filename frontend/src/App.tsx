import { useState, useCallback } from 'react'
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
      <aside className="sidebar" aria-label="侧边栏">
        <div className="brand">
          <div className="brand-mark" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', fontWeight: 800, color: 'var(--accent)' }}>
            R
          </div>
          <div>
            <strong>RAG News</strong>
            <span>AI intelligence</span>
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

        <div style={{ marginTop: 'auto', paddingTop: '12px', borderTop: '1px solid var(--sidebar-line)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 4px' }}>
            <span style={{ fontSize: '12px', color: 'var(--muted)' }}>{user?.email}</span>
            <button onClick={logout} className="ghost-button" style={{ height: '28px', padding: '0 12px', fontSize: '12px' }}>
              退出
            </button>
          </div>
        </div>
      </aside>

      <main className="chat-panel">
        <header className="chat-header">
          <div>
            <p className="eyebrow">RAG-powered news Q&amp;A</p>
            <h1>RAG News</h1>
            <div className="context-strip" aria-label="当前状态">
              <span>Multi-source retrieval</span>
            </div>
            <p className="header-copy">Ask questions about news articles. I&apos;ll search through sources and provide answers with citations.</p>
          </div>
          <div className="header-actions">
            <HealthBadge />
          </div>
        </header>

        <ChatWindow onSourcesUpdate={handleSourcesUpdate} externalQuery={externalQuery} onExternalQueryConsumed={() => setExternalQuery('')} />
        <ResearchPanel />
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
