import type { Source } from '../types'
import SourceCard from './SourceCard'

interface SourcePanelProps {
  sources: Source[]
}

/**
 * 来源面板组件
 * 展示检索到的相关文章列表，使用 SourceCard 渲染
 * Clean Light 风格，Tailwind CSS
 */
export default function SourcePanel({ sources }: SourcePanelProps) {
  if (sources.length === 0) {
    return (
      <div className="p-4 text-center text-gray-500 text-sm">
        暂无来源。输入问题以查看相关文章。
      </div>
    )
  }

  return (
    <div className="p-4 space-y-3 overflow-y-auto max-h-full">
      {sources.map((source, idx) => (
        <SourceCard
          key={idx}
          article={{
            id: idx,
            title: source.title,
            content: source.content,
            source: source.source,
            category: source.category,
            language: 'unknown',
            published_at: source.published_at || Date.now() / 1000,
            score: source.score,
            url: source.url
          }}
        />
      ))}
    </div>
  )
}
