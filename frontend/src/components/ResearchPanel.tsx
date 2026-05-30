import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { createResearchTask, researchEventsUrl } from '../api/client'
import type { ResearchTaskResponse } from '../types'

export default function ResearchPanel() {
  const [query, setQuery] = useState('')
  const [task, setTask] = useState<ResearchTaskResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sourceRef = useRef<EventSource | null>(null)

  useEffect(() => () => sourceRef.current?.close(), [])

  const startResearch = async () => {
    if (!query.trim() || running) return
    setRunning(true)
    setError(null)
    setTask(null)
    try {
      const created = await createResearchTask(query.trim())
      setTask(created)
      const events = new EventSource(researchEventsUrl(created.task_id))
      sourceRef.current = events
      events.addEventListener('progress', event => {
        const payload = JSON.parse((event as MessageEvent).data) as ResearchTaskResponse
        setTask(payload)
        if (payload.status === 'completed' || payload.status === 'failed') {
          setRunning(false)
          events.close()
        }
      })
      events.onerror = () => {
        setRunning(false)
        events.close()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建研究任务失败')
      setRunning(false)
    }
  }

  const logs = task?.execution_log || []
  const slides = task?.ppt_outline?.slides || []

  return (
    <section className="research-panel" aria-label="深度研究">
      <div className="section-heading">
        <h2>深度研究</h2>
      </div>
      <div className="research-composer">
        <textarea
          rows={3}
          value={query}
          onChange={event => setQuery(event.target.value)}
          placeholder="输入长期研究目标或本次研究任务..."
          disabled={running}
        />
        <button className="primary-button" onClick={startResearch} disabled={running || !query.trim()}>
          {running ? '研究中' : '开始研究'}
        </button>
      </div>
      {error && <p className="panel-error">{error}</p>}
      {task && (
        <div className="research-output">
          <div className="research-status">
            <span>{task.status}</span>
            <span>{task.current_step || 'queued'}</span>
            <span>{task.sources_used || 0} sources</span>
          </div>
          <div className="research-log">
            {logs.map((item, index) => (
              <span key={`${item.step}-${index}`}>{item.step}: {item.status}</span>
            ))}
          </div>
          {task.quality_report && (
            <pre className="quality-box">{JSON.stringify(task.quality_report, null, 2)}</pre>
          )}
          {task.result_markdown && (
            <div className="markdown-report">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{task.result_markdown}</ReactMarkdown>
            </div>
          )}
          {slides.length > 0 && (
            <div className="ppt-outline">
              <h3>{task.ppt_outline?.title || 'PPT 大纲'}</h3>
              {slides.slice(0, 8).map(slide => (
                <article key={slide.page}>
                  <strong>{slide.page}. {slide.title}</strong>
                  <ul>
                    {(slide.bullets || []).map((bullet, index) => <li key={index}>{bullet}</li>)}
                  </ul>
                </article>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
