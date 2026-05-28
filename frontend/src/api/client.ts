import type { HealthResponse, IngestTriggerResponse, IngestStatusResponse, QueryRequest, QueryResponse, Source, LoginRequest, RegisterRequest, AuthResponse, RefreshRequest, RefreshResponse, UserInfo, ResearchTaskResponse } from '../types'

const API_BASE = '/api'

export type { QueryRequest, QueryResponse, Source }

export interface Stats {
  total_articles: number
  total_chunks?: number
  sources: Record<string, number>
  categories: Record<string, number>
  languages: Record<string, number>
  last_updated?: string | null
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
    headers: {
      ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
      ...(options?.headers || {}),
    },
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

export async function login(req: LoginRequest): Promise<AuthResponse> {
  const res = await fetchWithErrorHandling<AuthResponse>(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (res.access_token) {
    localStorage.setItem('access_token', res.access_token)
    localStorage.setItem('refresh_token', res.refresh_token)
    localStorage.setItem('user', JSON.stringify(res.user))
  }
  return res
}

export async function register(req: RegisterRequest): Promise<AuthResponse> {
  const res = await fetchWithErrorHandling<AuthResponse>(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (res.access_token) {
    localStorage.setItem('access_token', res.access_token)
    localStorage.setItem('refresh_token', res.refresh_token)
    localStorage.setItem('user', JSON.stringify(res.user))
  }
  return res
}

export async function logout() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('user')
}

export function getStoredUser(): UserInfo | null {
  const u = localStorage.getItem('user')
  return u ? JSON.parse(u) : null
}

export function getAccessToken(): string | null {
  return localStorage.getItem('access_token')
}

export async function refreshToken(req: RefreshRequest): Promise<RefreshResponse> {
  return fetchWithErrorHandling<RefreshResponse>(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
}

export async function createResearchTask(query: string): Promise<ResearchTaskResponse> {
  return fetchWithErrorHandling<ResearchTaskResponse>(`${API_BASE}/research`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, output_format: 'both', time_window: 'last_3_months', top_k: 10 }),
  })
}

export function researchEventsUrl(taskId: string): string {
  const token = getAccessToken()
  return `${API_BASE}/research/${taskId}/events?token=${encodeURIComponent(token || '')}`
}
