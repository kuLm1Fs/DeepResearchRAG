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
      if (document.visibilityState === 'hidden') return
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
    const onVisibility = () => {
      if (document.visibilityState === 'visible') checkHealth()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      mounted = false
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  const getStatusClass = () => {
    if (loading || !health) return ''
    return health.status === 'healthy' ? 'healthy' : health.status === 'degraded' ? 'degraded' : 'unhealthy'
  }

  const getStatusText = () => {
    if (loading) return 'Checking...'
    if (!health) return 'Unknown'
    return health.status === 'healthy' ? 'Healthy' : 'Unhealthy'
  }

  return (
    <div className={`health-badge ${className}`}>
      <span className={`health-dot ${getStatusClass()}`}></span>
      {getStatusText()}
    </div>
  )
}
