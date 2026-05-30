import { useState, useRef, useEffect, useCallback, memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getAccessToken } from '../api/client'
import ErrorBoundary from './ErrorBoundary'
import type { Message, Source } from '../types'

const AVATAR_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='20' fill='%23171312'/%3E%3Ctext x='50' y='68' font-size='50' font-weight='bold' text-anchor='middle' fill='white'%3ER%3C/text%3E%3C/svg%3E"

interface MessageBubbleProps {
  message: Message
}

const MessageBubble = memo(function MessageBubble({ message }: MessageBubbleProps) {
  return (
    <article className={`message ${message.role}`}>
      {message.role === 'assistant' && (
        <img className="avatar" src={AVATAR_SVG} alt="" aria-hidden="true" />
      )}
      <div className="bubble">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
      </div>
    </article>
  )
})

interface ChatWindowProps {
  onSourcesUpdate: (sources: Source[]) => void
  externalQuery?: string
  onExternalQueryConsumed?: () => void
}

export default function ChatWindow({ onSourcesUpdate, externalQuery, onExternalQueryConsumed }: ChatWindowProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (externalQuery) {
      setInput(externalQuery)
      onExternalQueryConsumed?.()
    }
  }, [externalQuery, onExternalQueryConsumed])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const appendAssistantMessage = (content: string, isError = false) => {
    setMessages(prev => [...prev, { role: 'assistant', content, isError }])
  }

  const updateLastAssistantMessage = (content: string, isError = false) => {
    setMessages(prev => {
      const newMessages = [...prev]
      const lastIndex = newMessages.length - 1

      if (lastIndex >= 0 && newMessages[lastIndex].role === 'assistant') {
        newMessages[lastIndex] = { role: 'assistant', content, isError }
        return newMessages
      }

      return [...prev, { role: 'assistant', content, isError }]
    })
  }

  const formatErrorMessage = (err: unknown) => {
    if (err instanceof DOMException && err.name === 'TimeoutError') {
      return 'Request timed out. Please try again.'
    }
    if (err instanceof Error) {
      return err.message
    }
    return 'Unknown error'
  }

  const handleSubmit = useCallback(async (e: React.FormEvent | React.MouseEvent) => {
    if ('preventDefault' in e) e.preventDefault()
    if (!input.trim() || loading) return

    const userMessage = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setLoading(true)

    try {
      const response = await fetch('/api/query', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
        },
        body: JSON.stringify({ query: userMessage, top_k: 5, stream: true }),
        signal: AbortSignal.timeout(30000),
      })

      if (!response.ok) {
        const errorText = await response.text().catch(() => 'Unknown error')
        throw new Error(`HTTP ${response.status}: ${errorText}`)
      }

      if (!response.body) {
        throw new Error('Response body is empty')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let assistantMessage = ''
      let buffer = ''

      appendAssistantMessage('')

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6))

              if (event.type === 'sources') {
                onSourcesUpdate(event.data)
              } else if (event.type === 'token') {
                assistantMessage += event.data
                updateLastAssistantMessage(assistantMessage)
              } else if (event.type === 'done' && !assistantMessage) {
                assistantMessage = event.data?.answer || ''
                updateLastAssistantMessage(assistantMessage)
              } else if (event.type === 'error') {
                throw new Error(event.data || 'Streaming error')
              }
            } catch (err) {
              if (err instanceof SyntaxError) {
                console.warn('[DEBUG] Skipping malformed SSE payload:', line)
                continue
              }
              throw err
            }
          }
        }
      }
    } catch (err) {
      console.error('[DEBUG] Query failed:', err)
      updateLastAssistantMessage(`Error: ${formatErrorMessage(err)}`, true)
    } finally {
      setLoading(false)
    }
  }, [input, loading, onSourcesUpdate])

  return (
    <>
      <section className="messages" aria-label="对话内容">
        <ErrorBoundary fallback={<div style={{ padding: '24px', textAlign: 'center', color: 'var(--muted)' }}>Message rendering error. Please refresh.</div>}>
        {messages.length === 0 && (
          <div className="empty-state">
            <h2>Ask me anything</h2>
            <p>Search through news articles and get answers with source citations.</p>
          </div>
        )}

        {messages.map((msg, idx) => (
          <MessageBubble key={idx} message={msg} />
        ))}

        {loading && (
          <article className="message assistant">
            <img className="avatar" src={AVATAR_SVG} alt="" aria-hidden="true" />
            <div className="bubble">
              <div className="loading-dots">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </article>
        )}

        <div ref={messagesEndRef} />
        </ErrorBoundary>
      </section>

      <form className="composer" aria-label="发送消息">
        <div className="composer-box">
          <textarea
            id="promptInput"
            rows={1}
            placeholder="Ask a question about the news..."
            aria-label="输入消息"
            value={input}
            onChange={e => setInput(e.target.value)}
            disabled={loading}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSubmit(e)
              }
            }}
          />
          <button className="send-button" type="submit" aria-label="发送消息" onClick={handleSubmit} disabled={loading || !input.trim()}>
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </form>
    </>
  )
}
