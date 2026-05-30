import { useState } from 'react'
import type { Source } from '../types'

interface SourceCardProps {
  source: Source
  compact?: boolean
}

export default function SourceCard({ source, compact = false }: SourceCardProps) {
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

      {expanded && !compact && (
        <div className="source-card-expanded">
          <p className="source-card-content">
            {source.content.length > 200 ? source.content.slice(0, 200) + '...' : source.content}
          </p>
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
