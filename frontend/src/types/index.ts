/**
 * 核心类型定义
 */

// 消息类型
export interface Message {
  role: 'user' | 'assistant'
  content: string
  isError?: boolean
}

// 查询请求类型
export interface QueryRequest {
  query: string
  top_k?: number
  language?: string
  category?: string
  stream?: boolean
}

// 查询响应类型
export interface QueryResponse {
  answer: string
  sources: Source[]
  trace_id: string
}

// 来源类型
export interface Source {
  title: string
  content: string
  source: string
  category: string
  score: number
  url?: string
  published_at?: number
  language?: string
}

// 历史记录类型
export interface HistoryItem {
  id: string
  query: string
  timestamp: number
  sourceCount: number
}

// 统计数据类型
export interface StatsData {
  totalArticles: number
  totalChunks: number
  sources: string[]
  categories: string[]
  lastUpdated: string | null
}

// 健康检查响应类型
export interface HealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown'
  milvus_connected: boolean
  llm_provider: string
}

// 数据导入触发请求类型
export interface IngestTriggerRequest {
  source?: 'rss' | 'hackernews' | 'huggingface'
  limit?: number
}

// 数据导入触发响应类型
export interface IngestTriggerResponse {
  status: 'started' | 'error' | string
  source: string | null
  message: string
  task_id?: string | null
  articles_collected: number
  chunks_indexed?: number
  records_inserted?: number
}

// 数据导入状态响应类型
export interface IngestStatusResponse {
  total_articles: number
  sources: Record<string, number>
  collectors: string[]
}

// Auth Types
export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  company_name?: string
}

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: UserInfo
}

export interface UserInfo {
  id: string
  email: string
  role: string
  company_id: string | null
}

export interface RefreshRequest {
  refresh_token: string
}

export interface RefreshResponse {
  access_token: string
  token_type: string
}

export interface ResearchTaskResponse {
  task_id: string
  status: string
  message?: string
  current_step?: string
  plan?: Record<string, unknown>
  result_markdown?: string
  ppt_outline?: {
    title?: string
    slides?: Array<{ page: number; title: string; bullets: string[] }>
  }
  quality_report?: Record<string, unknown>
  execution_log?: Array<{ step: string; status: string; tool_call_count?: number }>
  sources_used?: number
}
