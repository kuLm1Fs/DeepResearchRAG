import type { Article } from '../types'
import SourceCard from './SourceCard'

interface CompareViewProps {
  articles: Article[]
  /** 可选的点击处理函数 */
  onArticleClick?: (article: Article) => void
}

/**
 * 多源对比视图
 * 并排展示多篇文章卡片，方便用户对比不同来源的报道
 * Clean Light 风格，Tailwind CSS
 */
export default function CompareView({ articles, onArticleClick }: CompareViewProps) {
  if (articles.length === 0) {
    return (
      <div className="p-6 text-center text-gray-500 text-sm">
        暂无文章可供对比
      </div>
    )
  }

  return (
    <div className="p-4">
      {/* 对比视图标题 */}
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-900">多源对比 ({articles.length} 篇)</h3>
        <p className="text-xs text-gray-500 mt-1">点击卡片展开查看详情</p>
      </div>

      {/* 并排卡片网格 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {articles.map((article, idx) => (
          <SourceCard
            key={article.id || idx}
            article={article}
            onClick={onArticleClick}
            showScore={true}
          />
        ))}
      </div>
    </div>
  )
}
