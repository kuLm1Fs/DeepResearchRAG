import { useState } from 'react'

interface Source {
  title: string
  content: string
  source: string
  category: string
  score: number
}

interface SourceCardProps {
  source: Source
}

function SourceCard({ source }: SourceCardProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div
      className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h4 className="font-medium text-gray-900 text-sm">{source.title}</h4>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-gray-500">{source.source}</span>
            <span className="text-xs px-2 py-0.5 bg-gray-100 rounded">{source.category}</span>
          </div>
        </div>
        <span className="text-xs text-gray-400">
          {(source.score * 100).toFixed(0)}%
        </span>
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <p className="text-sm text-gray-600 line-clamp-3">{source.content}</p>
        </div>
      )}
    </div>
  )
}

interface SourcePanelProps {
  sources: Source[]
}

export default function SourcePanel({ sources }: SourcePanelProps) {
  if (sources.length === 0) {
    return (
      <div className="p-4 text-center text-gray-500 text-sm">
        No sources yet. Ask a question to see relevant articles.
      </div>
    )
  }

  return (
    <div className="p-4 space-y-3 overflow-y-auto max-h-full">
      {sources.map((source, idx) => (
        <SourceCard key={idx} source={source} />
      ))}
    </div>
  )
}