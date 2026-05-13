import { useState, useEffect } from 'react'
import { ingestTrigger, getIngestStatus } from '../api/client'
import type { IngestStatusResponse, IngestTriggerResponse } from '../types'

const DATA_SOURCES = [
  { value: '', label: '全部 (All)' },
  { value: 'rss', label: 'RSS' },
  { value: 'hackernews', label: 'HackerNews' },
  { value: 'huggingface', label: 'HuggingFace' },
]

export default function IngestPanel() {
  const [source, setSource] = useState('')
  const [limit, setLimit] = useState(1000)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<IngestStatusResponse | null>(null)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const data = await getIngestStatus()
        setStatus(data)
      } catch {
        // Silently fail for status check
      }
    }
    fetchStatus()
  }, [])

  const handleTrigger = async () => {
    const normalizedLimit = Number.isFinite(limit) ? Math.min(Math.max(limit, 1), 10000) : 1000

    setLoading(true)
    setMessage(null)
    try {
      const result: IngestTriggerResponse = await ingestTrigger(source || undefined, normalizedLimit)
      if (result.status !== 'error') {
        setMessage({ type: 'success', text: result.message || `已采集: ${result.articles_collected} 条` })
        const data = await getIngestStatus()
        setStatus(data)
      } else {
        setMessage({ type: 'error', text: result.message || '导入失败' })
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error'
      setMessage({ type: 'error', text: `Error: ${errorMsg}` })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-4 border-b border-gray-200 bg-gray-50">
      <div className="text-sm font-medium text-gray-700 mb-3">数据导入</div>

      <div className="flex flex-col gap-3">
        <div className="flex gap-2">
          <select
            value={source}
            onChange={e => setSource(e.target.value)}
            className="flex-1 px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary"
          >
            {DATA_SOURCES.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <input
            type="number"
            value={limit}
            onChange={e => setLimit(Number(e.target.value))}
            placeholder="限制"
            min={1}
            max={10000}
            className="w-24 px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        <button
          onClick={handleTrigger}
          disabled={loading}
          className="w-full px-3 py-1.5 text-sm bg-primary text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? '导入中...' : '导入数据'}
        </button>

        {message && (
          <div
            className={`text-xs px-2 py-1.5 rounded ${
              message.type === 'success' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
            }`}
          >
            {message.text}
          </div>
        )}

        {status && (
          <div className="text-xs text-gray-500 mt-1">
            当前数据量: {status.total_articles} 条
            {status.collectors.length > 0 && (
              <span className="block mt-1">
                可用采集器: {status.collectors.join(', ')}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
