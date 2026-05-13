import { useState, useEffect } from 'react'
import { healthCheck } from '../api/client'
import type { HealthResponse } from '../types'

interface HealthBadgeProps {
  className?: string
}

export default function HealthBadge({ className = '' }: HealthBadgeProps) {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true

    const checkHealth = async () => {
      try {
        const data = await healthCheck()
        if (mounted) {
          setHealth(data)
        }
      } catch (err) {
        if (mounted) {
          setHealth({
            status: 'unhealthy',
            milvus_connected: false,
            llm_provider: err instanceof Error ? err.message : 'unknown',
          })
        }
      } finally {
        if (mounted) {
          setLoading(false)
        }
      }
    }

    checkHealth()
    const interval = setInterval(checkHealth, 30000)
    return () => {
      mounted = false
      clearInterval(interval)
    }
  }, [])

  const getStatusColor = () => {
    if (loading || !health) return 'bg-gray-400'
    return health.status === 'healthy' ? 'bg-green-500' : 'bg-red-500'
  }

  const getStatusText = () => {
    if (loading) return 'Checking...'
    if (!health) return 'Unknown'
    return health.status === 'healthy' ? 'Healthy' : 'Unhealthy'
  }

  const tooltipContent = health ? (
    <div className="text-left">
      <div>Milvus: {health.milvus_connected ? 'Connected' : 'Disconnected'}</div>
      <div>LLM: {health.llm_provider}</div>
    </div>
  ) : null

  return (
    <div className={`group relative inline-block ${className}`}>
      <div
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium text-white ${getStatusColor()}`}
      >
        <span className="w-2 h-2 rounded-full bg-white opacity-80" />
        {getStatusText()}
      </div>
      {tooltipContent && (
        <div className="absolute top-full left-0 mt-1 hidden group-hover:block z-50 bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-xs text-gray-700 whitespace-nowrap">
          {tooltipContent}
        </div>
      )}
    </div>
  )
}
