import type { Source } from '../types'
import SourceCard from './SourceCard'

interface SourcePanelProps {
  sources: Source[]
  compact?: boolean
}

export default function SourcePanel({ sources, compact = false }: SourcePanelProps) {
  if (sources.length === 0) {
    return (
      <div className="source-list">
        <div style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--faint)' }}>
          No sources yet
        </div>
      </div>
    )
  }

  const displaySources = compact ? sources.slice(0, 5) : sources

  return (
    <div className="source-list">
      {displaySources.map((source, idx) => (
        <SourceCard
          key={idx}
          source={source}
          compact={compact}
        />
      ))}
      {compact && sources.length > 5 && (
        <div style={{ textAlign: 'center', fontSize: '11px', color: 'var(--faint)', padding: '8px' }}>
          +{sources.length - 5} more sources
        </div>
      )}
    </div>
  )
}
