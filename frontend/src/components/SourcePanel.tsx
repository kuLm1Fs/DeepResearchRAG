import { lazy, Suspense, useState } from 'react'
import type { Source, GraphFacts } from '../types'
import SourceCard from './SourceCard'

// Lazy-load the graph viewer — react-force-graph-2d + d3-force is ~150KB
// and we don't want it on the initial bundle.
const GraphPanel = lazy(() => import('./GraphPanel'))

interface SourcePanelProps {
  sources: Source[]
  compact?: boolean
  graphFacts?: GraphFacts | null
}

type ViewMode = 'list' | 'graph'

export default function SourcePanel({ sources, compact = false, graphFacts = null }: SourcePanelProps) {
  const [view, setView] = useState<ViewMode>('list')

  // No sources AND no graph facts → show the placeholder regardless of view.
  if (sources.length === 0 && (!graphFacts || graphFacts.entities.length === 0)) {
    return (
      <div className="source-list">
        <div style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--faint)' }}>
          No sources yet
        </div>
      </div>
    )
  }

  return (
    <div className="source-list">
      <div className="source-panel-tabs" role="tablist">
        <button
          role="tab"
          aria-selected={view === 'list'}
          className={`source-panel-tab ${view === 'list' ? 'active' : ''}`}
          onClick={() => setView('list')}
        >
          List ({sources.length})
        </button>
        <button
          role="tab"
          aria-selected={view === 'graph'}
          className={`source-panel-tab ${view === 'graph' ? 'active' : ''}`}
          onClick={() => setView('graph')}
        >
          Graph
        </button>
      </div>

      {view === 'list' ? (
        <SourceList sources={sources} compact={compact} />
      ) : (
        <Suspense fallback={<div className="graph-panel-loading">Loading graph…</div>}>
          <GraphPanel facts={graphFacts} />
        </Suspense>
      )}
    </div>
  )
}

function SourceList({ sources, compact }: { sources: Source[]; compact: boolean }) {
  const displaySources = compact ? sources.slice(0, 5) : sources
  return (
    <>
      {displaySources.map((source, idx) => (
        <SourceCard key={idx} source={source} compact={compact} />
      ))}
      {compact && sources.length > 5 && (
        <div style={{ textAlign: 'center', fontSize: '11px', color: 'var(--faint)', padding: '8px' }}>
          +{sources.length - 5} more sources
        </div>
      )}
    </>
  )
}
