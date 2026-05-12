/**
 * 核心类型定义
 */

// 文章类型
export interface Article {
  id: number
  title: string
  content: string
  summary?: string
  source: string
  url?: string
  language: string
  category: string
  published_at: number
  score?: number
  tags?: string[]
}

// 消息类型
export interface Message {
  role: 'user' | 'assistant'
  content: string
}

// 查询请求类型
export interface QueryRequest {
  query: string
  filters?: FilterState
  stream?: boolean
}

// 查询响应类型
export interface QueryResponse {
  answer: string
  sources: Article[]
  trace_id: string
}

// 过滤状态类型
export interface FilterState {
  language: 'all' | 'zh' | 'en'
  dateRange: 'all' | 'today' | 'week' | 'month'
  sources: string[]
  category: string
}

// 来源类型（与 Article 兼容，用于兼容旧代码）
export interface Source {
  title: string
  content: string
  source: string
  category: string
  score: number
  url?: string
  published_at?: number
}
