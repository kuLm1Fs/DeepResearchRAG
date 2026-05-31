import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { createResearchTask, fetchResearchEvents, cancelResearchTask } from '../api/client'
import type { ResearchTaskResponse } from '../types'

const PIPELINE_STEPS = ['planner', 'retriever', 'analyst', 'checker', 'writer'] as const

function StepStepper({ currentStep, executionLog }: { currentStep?: string; executionLog?: Array<{ step: string; status: string; tool_call_count?: number }> }) {
  const completedSteps = new Set(
    (executionLog || []).filter(e => e.status === 'completed').map(e => e.step)
  )

  // Count retriever reruns (checker loops back to retriever)
  const retrieverRuns = (executionLog || []).filter(e => e.step === 'retriever').length

  return (
    <div className="step-stepper">
      {PIPELINE_STEPS.map((step, i) => {
        const isCompleted = completedSteps.has(step)
        const isActive = currentStep === step

        return (
          <div key={step} className={`step-item ${isCompleted ? 'completed' : isActive ? 'active' : ''}`}>
            <div className="step-dot">
              {isCompleted ? '✓' : isActive ? (
                <span className="step-spinner" />
              ) : i + 1}
            </div>
            <span className="step-label">
              {step}
              {step === 'retriever' && retrieverRuns > 1 && (
                <span className="step-badge">{retrieverRuns}x</span>
              )}
            </span>
            {i < PIPELINE_STEPS.length - 1 && <div className={`step-line ${isCompleted ? 'done' : ''}`} />}
          </div>
        )
      })}
    </div>
  )
}

function QualityReportView({ report, gaps, conflicts }: {
  report?: Record<string, unknown>
  gaps?: string[]
  conflicts?: Array<{ claim: string; sources: string[] }>
}) {
  if (!report) return null

  const coverage = report.evidence_coverage as number | undefined
  const diversity = report.source_diversity as string[] | string | undefined
  const freshness = report.freshness as string | undefined
  const credibility = report.credibility_issues as string[] | undefined

  return (
    <div className="quality-report">
      <h4>Quality Report</h4>
      <div className="quality-metrics">
        {coverage !== undefined && (
          <div className="quality-metric">
            <span className="metric-label">Evidence Coverage</span>
            <div className="metric-bar">
              <div className="metric-fill" style={{ width: `${Math.min(100, coverage * 100)}%` }} />
            </div>
            <span className="metric-value">{Math.round(coverage * 100)}%</span>
          </div>
        )}
        {diversity && (
          <div className="quality-metric">
            <span className="metric-label">Source Diversity</span>
            <div className="metric-tags">
              {(Array.isArray(diversity) ? diversity : [diversity]).map((s, i) => (
                <span key={i} className="metric-tag">{String(s)}</span>
              ))}
            </div>
          </div>
        )}
        {freshness && (
          <div className="quality-metric">
            <span className="metric-label">Freshness</span>
            <span className="metric-text">{String(freshness)}</span>
          </div>
        )}
      </div>
      {credibility && credibility.length > 0 && (
        <div className="quality-warnings">
          <h5>Credibility Issues</h5>
          <ul>
            {credibility.map((issue, i) => <li key={i}>{String(issue)}</li>)}
          </ul>
        </div>
      )}
      {gaps && gaps.length > 0 && (
        <div className="quality-warnings">
          <h5>Identified Gaps</h5>
          <ul>
            {gaps.map((gap, i) => <li key={i}>{gap}</li>)}
          </ul>
        </div>
      )}
      {conflicts && conflicts.length > 0 && (
        <div className="quality-warnings">
          <h5>Conflicts Detected</h5>
          <table className="conflicts-table">
            <thead>
              <tr><th>Claim</th><th>Sources</th></tr>
            </thead>
            <tbody>
              {conflicts.map((c, i) => (
                <tr key={i}>
                  <td>{c.claim}</td>
                  <td>{c.sources.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function ResearchPanel() {
  const [query, setQuery] = useState('')
  const [task, setTask] = useState<ResearchTaskResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => abortRef.current?.abort(), [])

  const startResearch = async () => {
    if (!query.trim() || running) return
    setRunning(true)
    setError(null)
    setTask(null)
    try {
      const created = await createResearchTask(query.trim())
      setTask(created)
      const controller = new AbortController()
      abortRef.current = controller

      fetchResearchEvents(
        created.task_id,
        (payload) => {
          setTask(payload)
          if (payload.status === 'completed' || payload.status === 'failed') {
            setRunning(false)
          }
        },
        (err) => {
          setError(err.message)
          setRunning(false)
        },
        controller.signal,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建研究任务失败')
      setRunning(false)
    }
  }

  const handleCancel = async () => {
    abortRef.current?.abort()
    if (!task?.task_id) return
    try {
      await cancelResearchTask(task.task_id)
    } catch {
      // ignore
    }
    setRunning(false)
  }

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
        <div className="research-actions">
          <button className="primary-button" onClick={startResearch} disabled={running || !query.trim()}>
            {running ? '研究中...' : '开始研究'}
          </button>
          {running && (
            <button className="ghost-button cancel-btn" onClick={handleCancel}>
              取消
            </button>
          )}
        </div>
      </div>
      {error && <p className="panel-error">{error}</p>}
      {task && (
        <div className="research-output">
          <StepStepper currentStep={task.current_step} executionLog={task.execution_log} />
          <div className="research-status">
            <span className={`status-badge status-${task.status}`}>{task.status}</span>
            <span>{task.sources_used || 0} sources</span>
          </div>
          {task.error_message && (
            <p className="panel-error">{task.error_message}</p>
          )}
          <QualityReportView
            report={task.quality_report}
            gaps={task.gaps_identified}
            conflicts={task.conflicts_detected}
          />
          {task.result_markdown && (
            <div className="markdown-report">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{task.result_markdown}</ReactMarkdown>
            </div>
          )}
          {slides.length > 0 && (
            <div className="ppt-outline">
              <h3>{task.ppt_outline?.title || 'PPT 大纲'}</h3>
              {slides.map(slide => (
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
