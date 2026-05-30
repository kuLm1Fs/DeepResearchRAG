import type { HealthResponse, IngestTriggerResponse, IngestStatusResponse, IngestTaskResponse, QueryRequest, QueryResponse, Source, LoginRequest, RegisterRequest, AuthResponse, UserInfo, ResearchTaskResponse } from '../types'

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

function getAuthHeaders(): Record<string, string> {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Token refresh state
let isRefreshing = false
let refreshQueue: Array<() => void> = []

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) return false

  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) return false
    const data = await res.json()
    if (data.access_token) {
      localStorage.setItem('access_token', data.access_token)
      return true
    }
    return false
  } catch {
    return false
  }
}

function clearAuthAndRedirect() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('user')
  window.location.href = '/login'
}

/**
 * 通用错误处理 fetch 工具函数，支持 401 自动刷新 token
 */
export async function fetchWithErrorHandling<T>(url: string, options?: RequestInit): Promise<T> {
  const timeoutSignal = AbortSignal.timeout(30000)
  const signal = options?.signal
    ? AbortSignal.any([options.signal, timeoutSignal])
    : timeoutSignal

  const doFetch = async (): Promise<Response> =>
    fetch(url, {
      ...options,
      headers: {
        ...getAuthHeaders(),
        ...(options?.headers || {}),
      },
      signal,
    })

  let response = await doFetch()

  // Handle 401 with token refresh
  if (response.status === 401) {
    if (isRefreshing) {
      // Wait for the in-progress refresh, then retry
      await new Promise<void>(resolve => refreshQueue.push(resolve))
      response = await doFetch()
    } else {
      isRefreshing = true
      const ok = await refreshAccessToken()
      isRefreshing = false
      // Wake up queued requests
      refreshQueue.forEach(resolve => resolve())
      refreshQueue = []

      if (ok) {
        response = await doFetch()
      } else {
        clearAuthAndRedirect()
        throw new Error('Session expired')
      }
    }
  }

  if (!response.ok) {
    const errorText = await response.text().catch(() => '')
    throw new Error(`HTTP ${response.status}: ${errorText || response.statusText || 'Unknown error'}`)
  }

  return response.json()
}

export async function query(request: QueryRequest): Promise<Response> {
  const doFetch = () =>
    fetch(`${API_BASE}/query`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify(request),
    })

  let response = await doFetch()

  if (response.status === 401) {
    if (isRefreshing) {
      await new Promise<void>(resolve => refreshQueue.push(resolve))
      response = await doFetch()
    } else {
      isRefreshing = true
      const ok = await refreshAccessToken()
      isRefreshing = false
      refreshQueue.forEach(resolve => resolve())
      refreshQueue = []
      if (ok) {
        response = await doFetch()
      } else {
        clearAuthAndRedirect()
        throw new Error('Session expired')
      }
    }
  }

  return response
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

export async function getIngestTask(taskId: string): Promise<IngestTaskResponse> {
  return fetchWithErrorHandling<IngestTaskResponse>(`${API_BASE}/ingest/task/${taskId}`)
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
  try {
    const u = localStorage.getItem('user')
    return u ? JSON.parse(u) : null
  } catch {
    return null
  }
}

export function getAccessToken(): string | null {
  return localStorage.getItem('access_token')
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

export async function cancelResearchTask(taskId: string): Promise<void> {
  await fetchWithErrorHandling<void>(`${API_BASE}/research/${taskId}/cancel`, {
    method: 'POST',
  })
}
