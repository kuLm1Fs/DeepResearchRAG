import type { FilterState } from '../types'

interface FilterBarProps {
  filters: FilterState
  onChange: (filters: FilterState) => void
}

/**
 * 过滤栏组件
 * 水平排列：语言过滤、时间范围、来源过滤
 * Clean Light 风格，Tailwind CSS
 */
export default function FilterBar({ filters, onChange }: FilterBarProps) {
  // 语言选项
  const languageOptions = [
    { value: 'all', label: '全部语言' },
    { value: 'zh', label: '中文' },
    { value: 'en', label: '英文' }
  ] as const

  // 时间范围选项
  const dateRangeOptions = [
    { value: 'all', label: '全部时间' },
    { value: 'today', label: '今天' },
    { value: 'week', label: '本周' },
    { value: 'month', label: '本月' }
  ] as const

  return (
    <div className="flex items-center gap-4 p-3 bg-white border-b border-gray-200 flex-wrap">
      {/* 语言过滤 */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500 font-medium">语言</span>
        <div className="flex gap-1">
          {languageOptions.map(option => (
            <button
              key={option.value}
              onClick={() => onChange({ ...filters, language: option.value })}
              className={`px-3 py-1 text-xs rounded-lg transition-colors ${
                filters.language === option.value
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {/* 分隔线 */}
      <div className="h-4 w-px bg-gray-200" />

      {/* 时间范围过滤 */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500 font-medium">时间</span>
        <div className="flex gap-1">
          {dateRangeOptions.map(option => (
            <button
              key={option.value}
              onClick={() => onChange({ ...filters, dateRange: option.value })}
              className={`px-3 py-1 text-xs rounded-lg transition-colors ${
                filters.dateRange === option.value
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {/* 分隔线 */}
      <div className="h-4 w-px bg-gray-200" />

      {/* 分类过滤 */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500 font-medium">分类</span>
        <select
          value={filters.category}
          onChange={e => onChange({ ...filters, category: e.target.value })}
          className="px-3 py-1 text-xs rounded-lg border border-gray-200 bg-white text-gray-600 hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        >
          <option value="">全部分类</option>
          <option value="tech">科技</option>
          <option value="business">商业</option>
          <option value="sports">体育</option>
          <option value="entertainment">娱乐</option>
          <option value="world">国际</option>
        </select>
      </div>

      {/* 来源过滤（多选） */}
      {filters.sources.length > 0 && (
        <>
          <div className="h-4 w-px bg-gray-200" />
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500 font-medium">来源</span>
            <div className="flex gap-1 flex-wrap">
              {filters.sources.map(source => (
                <span
                  key={source}
                  className="px-2 py-1 text-xs bg-gray-100 text-gray-600 rounded-lg"
                >
                  {source}
                </span>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
