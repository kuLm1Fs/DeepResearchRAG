import { useState } from 'react'
import type { Article } from '../types'

interface SourceCardProps {
  article: Article
  /** 可选的点击处理函数 */
  onClick?: (article: Article) => void
  /** 是否显示分数，默认 true */
  showScore?: boolean
}

/**
 * 折叠式来源卡片组件
 * 默认只显示标题和来源标签，点击展开显示内容、时间、分类、分数
 * Clean Light 风格，Tailwind CSS
 */
export default function SourceCard({ article, onClick, showScore = true }: SourceCardProps) {
  const [expanded, setExpanded] = useState(false)

  // 格式化时间戳
  const formatTime = (timestamp: number): string => {
    const date = new Date(timestamp * 1000)
    return date.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  }

  // 语言标签颜色
  const getLanguageColor = (lang: string): string => {
    return lang === 'zh' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'
  }

  const handleClick = () => {
    if (onClick) {
      onClick(article)
    } else {
      setExpanded(!expanded)
    }
  }

  return (
    <div
      className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer bg-white"
      onClick={handleClick}
    >
      {/* 标题和来源标签行 */}
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <h4 className="font-medium text-gray-900 text-sm leading-snug">
            {article.title}
          </h4>
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <span className="text-xs text-gray-500">{article.source}</span>
            <span className={`text-xs px-2 py-0.5 rounded ${getLanguageColor(article.language)}`}>
              {article.language === 'zh' ? '中文' : '英文'}
            </span>
            <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded">
              {article.category}
            </span>
          </div>
        </div>

        {/* 分数显示 */}
        {showScore && article.score !== undefined && (
          <span className="text-xs font-medium text-gray-400 ml-2">
            {(article.score * 100).toFixed(0)}%
          </span>
        )}
      </div>

      {/* 展开内容 */}
      {expanded && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          {/* 内容摘要 */}
          <p className="text-sm text-gray-600 leading-relaxed">
            {article.content.length > 200
              ? article.content.slice(0, 200) + '...'
              : article.content}
          </p>

          {/* 元信息 */}
          <div className="flex items-center gap-4 mt-3 text-xs text-gray-400">
            {article.published_at && (
              <span>{formatTime(article.published_at)}</span>
            )}
            {article.tags && article.tags.length > 0 && (
              <div className="flex gap-1">
                {article.tags.slice(0, 3).map((tag, idx) => (
                  <span key={idx} className="px-1.5 py-0.5 bg-gray-50 rounded">
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* 原文链接 */}
          {article.url && (
            <a
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={e => e.stopPropagation()}
              className="inline-block mt-2 text-xs text-blue-600 hover:text-blue-800 hover:underline"
            >
              查看原文 →
            </a>
          )}
        </div>
      )}

      {/* 展开指示器 */}
      <div className="flex justify-center mt-2">
        <span className="text-gray-300 text-xs">
          {expanded ? '▲ 收起' : '▼ 展开'}
        </span>
      </div>
    </div>
  )
}
