import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message, Source } from '../types'

interface ChatWindowProps {
  onSourcesUpdate: (sources: Source[]) => void
}

export default function ChatWindow({ onSourcesUpdate }: ChatWindowProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
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
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 mt-20">
            <p className="text-lg">Ask me anything about the news!</p>
            <p className="text-sm mt-2">I'll search through the articles and provide answers with sources.</p>
          </div>
        )}

        {messages.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-xl px-4 py-3 rounded-lg ${
                msg.role === 'user'
                  ? 'bg-primary text-white'
                  : msg.isError
                  ? 'bg-red-100 text-red-700 border border-red-300'
                  : 'bg-gray-100 text-gray-900'
              }`}
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 px-4 py-3 rounded-lg">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSubmit} className="border-t border-gray-200 p-4">
        <div className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask a question about the news..."
            className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-6 py-3 bg-primary text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  )
}
