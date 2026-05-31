import { useState, useRef, useEffect, useCallback, memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getAccessToken, submitFeedback } from '../api/client'
import ErrorBoundary from './ErrorBoundary'
import type { Message, Source } from '../types'

const AVATAR_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='20' fill='%23171312'/%3E%3Ctext x='50' y='68' font-size='50' font-weight='bold' text-anchor='middle' fill='white'%3ER%3C/text%3E%3C/svg%3E"

const NEGATIVE_REASONS = ['irrelevant', 'outdated', 'wrong', 'incomplete'] as const

interface MessageBubbleProps {
  message: Message
  onFeedback?: (rating: 'positive' | 'negative', reason?: string) => void
}

const MessageBubble = memo(function MessageBubble({ message, onFeedback }: MessageBubbleProps) {
  const [showReasons, setShowReasons] = useState(false)

  const handleFeedback = (rating: 'positive' | 'negative') => {
    if (message.feedback) return // already submitted
    if (rating === 'negative') {
      setShowReasons(true)
      return
    }
    onFeedback?.('positive')
  }

  const handleReason = (reason: string) => {
    setShowReasons(false)
    onFeedback?.('negative', reason)
  }

  return (
    <article className={`message ${message.role}`}>
      {message.role === 'assistant' && (
        <img className="avatar" src={AVATAR_SVG} alt="" aria-hidden="true" />
      )}
      <div className="message-body">
        <div className="bubble">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
        </div>
        {message.role === 'assistant' && !message.isError && message.content && (
          <div className="feedback-bar">
            {message.feedback ? (
              <span className="feedback-thanks">
                {message.feedback === 'positive' ? '👍 Thanks for the feedback' : '👎 Feedback recorded'}
              </span>
            ) : showReasons ? (
              <div className="feedback-reasons">
                {NEGATIVE_REASONS.map(r => (
                  <button key={r} className="feedback-reason-btn" onClick={() => handleReason(r)}>
                    {r}
                  </button>
                ))}
                <button className="feedback-reason-btn cancel" onClick={() => setShowReasons(false)}>cancel</button>
              </div>
            ) : (
              <div className="feedback-buttons">
                <button
                  className="feedback-btn"
                  aria-label="Good answer"
                  onClick={() => handleFeedback('positive')}
                  title="Good answer"
                >
                  👍
                </button>
                <button
                  className="feedback-btn"
                  aria-label="Bad answer"
                  onClick={() => handleFeedback('negative')}
                  title="Bad answer"
                >
                  👎
                </button>
              </div>
            )}
          </div>
        )}
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
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (externalQuery) {
      setInput(externalQuery)
      onExternalQueryConsumed?.()
    }
  }, [externalQuery, onExternalQueryConsumed])

  // Cleanup on unmount
  useEffect(() => () => { abortRef.current?.abort() }, [])

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 180) + 'px'
  }, [input])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const appendAssistantMessage = (content: string, isError = false) => {
    setMessages(prev => [...prev, { role: 'assistant', content, isError }])
  }

  const updateLastAssistantMessage = (content: string, isError = false, traceId?: string) => {
    setMessages(prev => {
      const newMessages = [...prev]
      const lastIndex = newMessages.length - 1

      if (lastIndex >= 0 && newMessages[lastIndex].role === 'assistant') {
        newMessages[lastIndex] = { ...newMessages[lastIndex], content, isError, traceId: traceId || newMessages[lastIndex].traceId }
        return newMessages
      }

      return [...prev, { role: 'assistant', content, isError, traceId }]
    })
  }

  const formatErrorMessage = (err: unknown) => {
    if (err instanceof DOMException && err.name === 'AbortError') {
      return 'Generation stopped.'
    }
    if (err instanceof DOMException && err.name === 'TimeoutError') {
      return 'Request timed out. Please try again.'
    }
    if (err instanceof Error) {
      return err.message
    }
    return 'Unknown error'
  }

  const stopGeneration = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  const handleSubmit = useCallback(async (e: React.FormEvent | React.MouseEvent) => {
    if ('preventDefault' in e) e.preventDefault()
    if (!input.trim() || loading) return

    const userMessage = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setLoading(true)

    const MAX_RETRIES = 3
    let lastErr: unknown

    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      if (attempt > 0) {
        // Exponential backoff: 1s, 2s, 4s
        await new Promise(r => setTimeout(r, 1000 * Math.pow(2, attempt - 1)))
        updateLastAssistantMessage(`Retrying (${attempt}/${MAX_RETRIES})...`)
      }

      const controller = new AbortController()
      abortRef.current = controller

      try {
        const response = await fetch('/api/query', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
          },
          body: JSON.stringify({
            query: userMessage,
            top_k: 5,
            stream: true,
            ...(dateFrom ? { date_from: Math.floor(new Date(dateFrom).getTime() / 1000) } : {}),
            ...(dateTo ? { date_to: Math.floor(new Date(dateTo).getTime() / 1000) + 86399 } : {}),
          }),
          signal: controller.signal,
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

        if (attempt === 0) appendAssistantMessage('')

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
                } else if (event.type === 'done') {
                  if (!assistantMessage) {
                    assistantMessage = event.data?.answer || ''
                  }
                  updateLastAssistantMessage(assistantMessage, false, event.data?.trace_id)
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

        // Success — break out of retry loop
        lastErr = null
        break
      } catch (err) {
        // Don't retry on abort (user clicked Stop)
        if (err instanceof DOMException && err.name === 'AbortError') {
          updateLastAssistantMessage('Generation stopped.', true)
          lastErr = null
          break
        }
        lastErr = err
        console.warn(`[DEBUG] Query attempt ${attempt + 1} failed:`, err)
      }
    }

    if (lastErr) {
      console.error('[DEBUG] Query failed after retries:', lastErr)
      updateLastAssistantMessage(`Error: ${formatErrorMessage(lastErr)}`, true)
    }

    abortRef.current = null
    setLoading(false)
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
          <MessageBubble
            key={idx}
            message={msg}
            onFeedback={msg.role === 'assistant' ? async (rating, reason) => {
              setMessages(prev => {
                const copy = [...prev]
                copy[idx] = { ...copy[idx], feedback: rating }
                return copy
              })
              try {
                await submitFeedback({
                  query_id: msg.traceId,
                  query_text: messages[idx - 1]?.role === 'user' ? messages[idx - 1].content : undefined,
                  rating,
                  reason,
                })
              } catch (err) {
                console.warn('[DEBUG] Feedback submission failed:', err)
              }
            } : undefined}
          />
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
        {showFilters && (
          <div className="date-filter">
            <label>
              <span>From</span>
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
            </label>
            <label>
              <span>To</span>
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} />
            </label>
            {(dateFrom || dateTo) && (
              <button type="button" className="ghost-button" onClick={() => { setDateFrom(''); setDateTo('') }}>Clear</button>
            )}
          </div>
        )}
        <div className="composer-box">
          <textarea
            ref={textareaRef}
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
          {loading ? (
            <button className="send-button stop-button" type="button" aria-label="停止生成" onClick={stopGeneration} title="Stop">
              <span aria-hidden="true">■</span>
            </button>
          ) : (
            <>
              <button
                type="button"
                className={`send-button filter-toggle${showFilters ? ' active' : ''}`}
                aria-label="Toggle date filter"
                onClick={() => setShowFilters(f => !f)}
                title="Date filter"
              >
                <span aria-hidden="true">⚙</span>
              </button>
              <button className="send-button" type="submit" aria-label="发送消息" onClick={handleSubmit} disabled={!input.trim()}>
                <span aria-hidden="true">→</span>
              </button>
            </>
          )}
        </div>
      </form>
    </>
  )
}
