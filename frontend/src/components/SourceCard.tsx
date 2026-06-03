import { useState } from 'react'
import type { Source } from '../types'

interface SourceCardProps {
  source: Source
  compact?: boolean
  // Phase 5: relations surfaced by the graph retrieval path. Optional —
  // vector-only chunks simply don't pass this prop.
  relations?: Array<{ source: string; target: string; type: string }>
  // Phase 5: entities this chunk mentions, for the "tag" line under the
  // source metadata.
  entities?: Array<{ name: string; type?: string | null }>
}

export default function SourceCard({ source, compact = false, relations, entities }: SourceCardProps) {
  const [expanded, setExpanded] = useState(false)

  const formatTime = (timestamp: number): string => {
    const date = new Date(timestamp * 1000)
    return date.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  }

  const handleClick = () => {
    if (!compact) {
      setExpanded(!expanded)
    }
  }

  const langClass = source.language === 'zh' ? 'lang-zh' : 'lang-en'
  const langLabel = source.language === 'zh' ? '中文' : '英文'

  // Normalize & dedupe the relations list — different code paths can
  // surface the same edge twice.
  const relationChips = relations
    ? Array.from(
        new Map(
          relations.map(r => [
            `${r.source}|${r.type}|${r.target}`,
            r,
          ])
        ).values()
      ).slice(0, 4)
    : []

  return (
    <div className="source-card" onClick={handleClick}>
      <div className="source-card-title">{source.title}</div>

      <div className="source-card-meta">
        <span className="source-card-tag">{source.source}</span>
        <span className={`source-card-tag ${langClass}`}>{langLabel}</span>
        <span className="source-card-tag">{source.category}</span>
        {source.score !== undefined && (
          <span className="source-card-score">{(source.score * 100).toFixed(0)}%</span>
        )}
      </div>

      {entities && entities.length > 0 && (
        <div className="source-card-entities">
          {entities.slice(0, 4).map((e, i) => (
            <span key={`${e.name}-${i}`} className="source-card-entity-chip">
              {e.name}
            </span>
          ))}
          {entities.length > 4 && (
            <span className="source-card-entity-chip more">+{entities.length - 4}</span>
          )}
        </div>
      )}

      {expanded && !compact && (
        <div className="source-card-expanded">
          <p className="source-card-content">
            {source.content.length > 200 ? source.content.slice(0, 200) + '...' : source.content}
          </p>
          {relationChips.length > 0 && (
            <div className="source-card-relations">
              <span className="source-card-relations-label">Graph relations:</span>
              {relationChips.map((r, i) => (
                <span key={i} className="source-card-relation-chip" title={r.type}>
                  {r.source} <span className="rel-type">→{r.type}→</span> {r.target}
                </span>
              ))}
            </div>
          )}
          <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--faint)' }}>
            {source.published_at && formatTime(source.published_at)}
          </div>
          {source.url && (
            <a href={source.url} target="_blank" rel="noopener noreferrer" className="source-card-link" onClick={e => e.stopPropagation()}>
              查看原文 →
            </a>
          )}
        </div>
      )}

      {!compact && (
        <div className="expand-indicator">
          {expanded ? '▲ 收起' : '▼ 展开'}
        </div>
      )}
    </div>
  )
}
