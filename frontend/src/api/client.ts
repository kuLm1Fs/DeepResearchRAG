const API_BASE = '/api'

export interface QueryRequest {
  query: string
  top_k?: number
  language?: string
  category?: string
  stream?: boolean
}

export interface Source {
  title: string
  content: string
  source: string
  category: string
  score: number
}

export interface QueryResponse {
  answer: string
  sources: Source[]
  trace_id: string
}

export interface Stats {
  total_articles: number
  sources: Record<string, number>
  categories: Record<string, number>
  languages: Record<string, number>
}

export async function query(request: QueryRequest): Promise<Response> {
  return fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export async function getStats(): Promise<Stats> {
  const response = await fetch(`${API_BASE}/stats`)
  return response.json()
}

export async function healthCheck(): Promise<{ status: string; milvus_connected: boolean }> {
  const response = await fetch(`${API_BASE}/health`)
  return response.json()
}