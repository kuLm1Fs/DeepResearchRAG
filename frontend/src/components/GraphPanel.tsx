import { useEffect, useMemo, useRef, useState } from 'react'
import type { GraphFacts, GraphRelationRef } from '../types'
import { getEntitySubgraph } from '../api/client'

/**
 * Force-directed graph view for the entities/relations surfaced by the
 * GraphRAG retrieval path. Renders the local subgraph centered on the
 * entities in `facts`, expanding one node at a time on click via the
 * /api/graph/entity/{name} endpoint.
 *
 * The panel is intentionally split into a "facts" view (what came back
 * from the query) and a "browse" view (click an entity → fetch its 1-hop
 * neighborhood → merge into the visible graph). Lazy-loaded by App.tsx
 * via React.lazy so the ~150KB react-force-graph-2d bundle only ships
 * when the user opens this view.
 */
export interface GraphPanelProps {
  facts: GraphFacts | null
}

interface NodeShape {
  id: string
  name: string
  type?: string | null
  // Whether this node was part of the surfaced facts (vs expanded via click).
  primary: boolean
  // Whether this node is currently highlighted as belonging to the focused
  // chunk on the source panel.
  highlighted: boolean
}

interface LinkShape {
  source: string
  target: string
  type: string
  // Color weight: 0..1; 1 = primary relation from facts, <1 = expanded.
  weight: number
}

// Color the node by entity type. Falls back to a neutral grey when the
// backend didn't surface a type (typical for entities resolved only by name).
const TYPE_COLOR: Record<string, string> = {
  Company: '#2563eb',
  Person: '#9333ea',
  Product: '#ea580c',
  Event: '#db2777',
  Metric: '#16a34a',
  Location: '#0891b2',
  Concept: '#6b7280',
}

function colorForType(type?: string | null): string {
  if (!type) return '#6b7280'
  return TYPE_COLOR[type] ?? '#6b7280'
}

export default function GraphPanel({ facts }: GraphPanelProps) {
  const [extraNodes, setExtraNodes] = useState<NodeShape[]>([])
  const [extraLinks, setExtraLinks] = useState<LinkShape[]>([])
  const [loadingEntity, setLoadingEntity] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 400, h: 300 })

  // Resize observer so the canvas fits the panel as the sidebar grows.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        if (width > 0 && height > 0) {
          setSize({ w: Math.floor(width), h: Math.floor(height) })
        }
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Build base graph from the SSE facts. Memoized so unrelated state
  // updates (loading flags, etc.) don't recompute the layout.
  const base = useMemo(() => {
    if (!facts) return { nodes: [] as NodeShape[], links: [] as LinkShape[] }
    const primary = new Set(facts.entities.map(e => e.name))
    const nodes: NodeShape[] = facts.entities.map(e => ({
      id: e.entity_id || e.name,
      name: e.name,
      type: e.type,
      primary: true,
      highlighted: false,
    }))
    const links: LinkShape[] = facts.relations.map(r => ({
      source: r.source,
      target: r.target,
      type: r.type,
      weight: 1,
    }))
    return { nodes, links, primary } as const
  }, [facts])

  // Reset expansion when a new query comes in — otherwise stale neighbors
  // from the previous query linger.
  useEffect(() => {
    setExtraNodes([])
    setExtraLinks([])
    setErrorMsg(null)
  }, [facts])

  const allNodes = useMemo(() => {
    const seen = new Set<string>()
    const merged: NodeShape[] = []
    for (const n of [...base.nodes, ...extraNodes]) {
      if (seen.has(n.id)) continue
      seen.add(n.id)
      merged.push(n)
    }
    return merged
  }, [base.nodes, extraNodes])

  const allLinks = useMemo(() => {
    // Dedupe (source, target, type) — relations can be surfaced by both
    // the facts payload and the expansion endpoint.
    const seen = new Set<string>()
    const merged: LinkShape[] = []
    for (const l of [...base.links, ...extraLinks]) {
      const key = `${l.source}|${l.target}|${l.type}`
      if (seen.has(key)) continue
      seen.add(key)
      merged.push(l)
    }
    return merged
  }, [base.links, extraLinks])

  const onNodeClick = async (node: NodeShape) => {
    if (loadingEntity === node.id) return
    setLoadingEntity(node.id)
    setErrorMsg(null)
    try {
      const sub = await getEntitySubgraph(node.name)
      // Skip if we already have it (defensive — useMemo above would dedupe
      // visually, but this avoids re-fetching on repeated clicks).
      if (extraNodes.find(n => n.id === sub.entity_id)) {
        setLoadingEntity(null)
        return
      }
      const newNodes: NodeShape[] = sub.relations
        .filter((r: GraphRelationRef) => r.target_id && r.target_name)
        .map((r: GraphRelationRef) => ({
          id: r.target_id,
          name: r.target_name,
          type: r.target_type,
          primary: false,
          highlighted: false,
        }))
      const newLinks: LinkShape[] = sub.relations
        .filter((r: GraphRelationRef) => r.target_id)
        .map((r: GraphRelationRef) => ({
          source: sub.entity_id,
          target: r.target_id,
          type: r.type,
          weight: r.weight ?? 0.5,
        }))
      setExtraNodes(prev => [...prev, ...newNodes])
      setExtraLinks(prev => [...prev, ...newLinks])
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load entity'
      setErrorMsg(msg)
    } finally {
      setLoadingEntity(null)
    }
  }

  if (!facts) {
    return (
      <div className="graph-panel empty">
        <p>No graph data yet. Ask a question to see entities and relations.</p>
      </div>
    )
  }

  if (facts.entities.length === 0) {
    return (
      <div className="graph-panel empty">
        <p>
          The knowledge graph wasn't used for this query (strategy: <b>{facts.strategy}</b>).
        </p>
        <p style={{ fontSize: '12px', color: 'var(--faint)' }}>{facts.strategy_reason}</p>
      </div>
    )
  }

  return (
    <div className="graph-panel" ref={containerRef}>
      <div className="graph-panel-header">
        <span className="graph-panel-title">Knowledge Graph</span>
        <span className="graph-panel-meta">
          {allNodes.length} nodes · {allLinks.length} edges · {facts.strategy}
        </span>
      </div>
      <div className="graph-canvas-wrap" style={{ width: size.w, height: size.h }}>
        <GraphCanvas
          nodes={allNodes}
          links={allLinks}
          width={size.w}
          height={size.h}
          onNodeClick={onNodeClick}
        />
      </div>
      {loadingEntity && (
        <div className="graph-panel-status">Loading neighbors for {loadingEntity}…</div>
      )}
      {errorMsg && <div className="graph-panel-status error">{errorMsg}</div>}
      <div className="graph-panel-legend">
        {Object.entries(TYPE_COLOR).map(([type, color]) => (
          <span key={type} className="legend-item">
            <span className="legend-swatch" style={{ background: color }} />
            {type}
          </span>
        ))}
      </div>
    </div>
  )
}

// ----- Canvas wrapper -----
// react-force-graph-2d ships ESM that the TypeScript compiler is happy with
// but its types are awkward. We isolate it here so the panel compiles even
// if the upstream types drift.
function GraphCanvas(props: {
  nodes: NodeShape[]
  links: LinkShape[]
  width: number
  height: number
  onNodeClick: (node: NodeShape) => void
}) {
  // Dynamic import keeps this code-split from the main bundle.
  // (The lazy boundary in App.tsx ensures the user only downloads this
  // when they actually open the graph view.)
  const [Comp, setComp] = useState<React.ComponentType<ForceGraphProps> | null>(null)
  useEffect(() => {
    let cancelled = false
    import('react-force-graph-2d').then(mod => {
      if (!cancelled) setComp(() => mod.default as unknown as React.ComponentType<ForceGraphProps>)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const graphData = useMemo(
    () => ({
      nodes: props.nodes.map(n => ({ ...n })),
      links: props.links.map(l => ({ ...l })),
    }),
    [props.nodes, props.links]
  )

  if (!Comp) {
    return <div className="graph-canvas-loading">Loading graph…</div>
  }
  return (
    <Comp
      graphData={graphData}
      width={props.width}
      height={props.height}
      backgroundColor="transparent"
      nodeRelSize={5}
      linkColor={link => linkColorFor(link as LinkShape)}
      linkWidth={link => linkWidthFor(link as LinkShape)}
      linkDirectionalArrowLength={4}
      linkDirectionalArrowRelPos={0.9}
      nodeCanvasObject={drawNode}
      nodeCanvasObjectMode={() => 'replace'}
      onNodeClick={node => props.onNodeClick(node as NodeShape)}
      cooldownTicks={120}
      d3VelocityDecay={0.3}
    />
  )
}

// ---- Force-graph local types ----
// react-force-graph-2d's exported types are permissive but we narrow them
// here so the panel stays strict. Treats `any` from the lib as a
// structurally-typed union.
type ForceGraphNode = NodeShape & { x?: number; y?: number }
type ForceGraphLink = LinkShape

interface ForceGraphProps {
  graphData: { nodes: ForceGraphNode[]; links: ForceGraphLink[] }
  width: number
  height: number
  backgroundColor: string
  nodeRelSize: number
  linkColor: (link: ForceGraphLink) => string
  linkWidth: (link: ForceGraphLink) => number
  linkDirectionalArrowLength: number
  linkDirectionalArrowRelPos: number
  nodeCanvasObject: (
    node: ForceGraphNode,
    ctx: CanvasRenderingContext2D,
    globalScale: number,
  ) => void
  nodeCanvasObjectMode: () => 'replace' | 'before' | 'after'
  onNodeClick: (node: ForceGraphNode) => void
  cooldownTicks: number
  d3VelocityDecay: number
}

function linkColorFor(link: LinkShape): string {
  return (link.weight ?? 0.5) >= 1
    ? 'rgba(37, 99, 235, 0.6)'
    : 'rgba(107, 114, 128, 0.4)'
}

function linkWidthFor(link: LinkShape): number {
  return (link.weight ?? 0.5) >= 1 ? 1.6 : 0.8
}

function drawNode(
  node: ForceGraphNode,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
): void {
  const label = node.name
  const fontSize = Math.max(10, 12 / globalScale)
  const color = colorForType(node.type)
  const radius = node.primary ? 6 : 4
  ctx.beginPath()
  ctx.arc(node.x ?? 0, node.y ?? 0, radius, 0, 2 * Math.PI, false)
  ctx.fillStyle = color
  ctx.fill()
  if (node.primary) {
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 1.5
    ctx.stroke()
  }
  // Label
  ctx.font = `${fontSize}px sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillStyle = '#1f2937'
  ctx.fillText(label, node.x ?? 0, (node.y ?? 0) + radius + 2)
}
