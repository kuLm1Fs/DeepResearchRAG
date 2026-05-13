import type { HealthResponse, IngestTriggerResponse, IngestStatusResponse, QueryRequest, QueryResponse, Source } from '../types'

const API_BASE = '/api'

export type { QueryRequest, QueryResponse, Source }

export interface Stats {
  total_articles: number
  sources: Record<string, number>
  categories: Record<string, number>
  languages: Record<string, number>
}

/**
 * 通用错误处理 fetch 工具函数
 */
export async function fetchWithErrorHandling<T>(url: string, options?: RequestInit): Promise<T> {
  const timeoutSignal = AbortSignal.timeout(30000)
  const signal = options?.signal
    ? AbortSignal.any([options.signal, timeoutSignal])
    : timeoutSignal

  const response = await fetch(url, {
    ...options,
    signal,
  })

  if (!response.ok) {
    const errorText = await response.text().catch(() => '')
    throw new Error(`HTTP ${response.status}: ${errorText || response.statusText || 'Unknown error'}`)
  }

  return response.json()
}

export async function query(request: QueryRequest): Promise<Response> {
  return fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export async function getStats(): Promise<Stats> {
  return fetchWithErrorHandling<Stats>(`${API_BASE}/stats`)
}

export async function healthCheck(): Promise<HealthResponse> {
  return fetchWithErrorHandling<HealthResponse>(`${API_BASE}/health`)
}

export async function ingestTrigger(source?: string, limit?: number): Promise<IngestTriggerResponse> {
  return fetchWithErrorHandling<IngestTriggerResponse>(`${API_BASE}/ingest/trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source: source || null, limit }),
  })
}

export async function getIngestStatus(): Promise<IngestStatusResponse> {
  return fetchWithErrorHandling<IngestStatusResponse>(`${API_BASE}/ingest/status`)
}
