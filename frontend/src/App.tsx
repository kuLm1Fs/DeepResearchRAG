import { useState } from 'react'
import ChatWindow from './components/ChatWindow'
import SourcePanel from './components/SourcePanel'

function App() {
  const [sources, setSources] = useState<any[]>([])
  const [panelCollapsed, setPanelCollapsed] = useState(false)

  return (
    <div className="flex h-screen">
      {/* Chat Area - 70% */}
      <div className="flex-1 flex flex-col">
        <header className="bg-white border-b border-gray-200 px-6 py-4">
          <h1 className="text-xl font-semibold text-gray-900">RAG News Intelligence</h1>
        </header>
        <ChatWindow onSourcesUpdate={setSources} />
      </div>

      {/* Source Panel - 30% */}
      <div className={`border-l border-gray-200 bg-white transition-all duration-300 ${panelCollapsed ? 'w-12' : 'w-96'}`}>
        <button
          onClick={() => setPanelCollapsed(!panelCollapsed)}
          className="w-full px-4 py-3 border-b border-gray-200 text-left text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          {panelCollapsed ? '→' : '←'} Sources ({sources.length})
        </button>
        {!panelCollapsed && <SourcePanel sources={sources} />}
      </div>
    </div>
  )
}

export default App