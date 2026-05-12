export interface Source {
  title: string
  content: string
  source: string
  category: string
  score: number
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
}

export interface QueryRequest {
  query: string
  top_k?: number
  language?: string
  category?: string
  stream?: boolean
}