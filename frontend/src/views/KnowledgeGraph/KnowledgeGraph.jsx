import { useState, useEffect, useCallback } from 'react'
import {
  ReactFlow,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  Panel,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Plus, Trash2, GitBranch, Loader2, Wand2 } from 'lucide-react'
import useWorkspaceStore from '../../stores/workspaceStore'
import useDataStore from '../../stores/dataStore'
import KpiMovementNode from './nodes/KpiMovementNode'
import EventNode from './nodes/EventNode'
import PolicyNode from './nodes/PolicyNode'
import InsightNode from './nodes/InsightNode'

const nodeTypes = {
  kpi_movement: KpiMovementNode,
  event: EventNode,
  policy: PolicyNode,
  insight: InsightNode,
}

const NODE_TEMPLATES = [
  { type: 'kpi_movement', label: 'KPI Movement', color: 'bg-blue-100 text-blue-700' },
  { type: 'event', label: 'Event', color: 'bg-red-100 text-red-700' },
  { type: 'policy', label: 'Policy', color: 'bg-green-100 text-green-700' },
  { type: 'insight', label: 'Insight', color: 'bg-purple-100 text-purple-700' },
]

const EDGE_TYPES = ['caused_by', 'correlated_with', 'led_to', 'sourced_from']

function mapNodeData(n) {
  return {
    id: n.id,
    type: n.node_type,
    position: { x: n.x || Math.random() * 600, y: n.y || Math.random() * 400 },
    data: { label: n.label, metadata: n.metadata, nodeType: n.node_type },
  }
}

function mapEdgeData(e) {
  return {
    id: e.id,
    source: e.source_id,
    target: e.target_id,
    label: e.label || e.edge_type.replace(/_/g, ' '),
    type: 'default',
    animated: e.edge_type === 'correlated_with',
    style: {
      stroke: e.edge_type === 'caused_by' ? '#2563eb'
        : e.edge_type === 'led_to' ? '#16a34a'
        : e.edge_type === 'sourced_from' ? '#94a3b8'
        : '#d97706',
      strokeDasharray: e.edge_type === 'correlated_with' ? '5 5' : undefined,
    },
  }
}

export default function KnowledgeGraph() {
  const workspace = useWorkspaceStore(s => s.activeWorkspace)
  const results = useDataStore(s => s.results)
  const selectedCountries = useDataStore(s => s.selectedCountries)

  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [selectedNode, setSelectedNode] = useState(null)
  const [edgeType, setEdgeType] = useState('caused_by')
  const [building, setBuilding] = useState(false)

  const wsId = workspace?.id

  useEffect(() => {
    if (!wsId) return
    Promise.all([
      fetch(`/api/workspaces/${wsId}/graph/nodes`).then(r => r.json()),
      fetch(`/api/workspaces/${wsId}/graph/edges`).then(r => r.json()),
    ]).then(([nodeData, edgeData]) => {
      setNodes(nodeData.map(mapNodeData))
      setEdges(edgeData.map(mapEdgeData))
    })
  }, [wsId, setNodes, setEdges])

  const autoBuild = async () => {
    if (!wsId || !results.length) return
    setBuilding(true)
    try {
      const resp = await fetch(`/api/workspaces/${wsId}/graph/auto-build`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ results, countries: selectedCountries }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setNodes(data.nodes.map(mapNodeData))
      setEdges(data.edges.map(mapEdgeData))
    } catch (e) {
      console.error('Auto-build failed:', e)
    } finally {
      setBuilding(false)
    }
  }

  const addNode = async (type) => {
    if (!wsId) return
    const label = window.prompt(`Enter label for ${type.replace(/_/g, ' ')}:`)
    if (!label) return

    const resp = await fetch(`/api/workspaces/${wsId}/graph/nodes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        node_type: type,
        label,
        x: 300 + Math.random() * 200,
        y: 200 + Math.random() * 200,
      }),
    })
    const node = await resp.json()
    setNodes(prev => [...prev, mapNodeData(node)])
  }

  const onConnect = useCallback(async (params) => {
    if (!wsId) return
    const resp = await fetch(`/api/workspaces/${wsId}/graph/edges`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_id: params.source,
        target_id: params.target,
        edge_type: edgeType,
        label: edgeType.replace(/_/g, ' '),
      }),
    })
    const edge = await resp.json()
    setEdges(prev => addEdge({
      ...params,
      id: edge.id,
      label: edge.label || edge.edge_type.replace(/_/g, ' '),
      animated: edge.edge_type === 'correlated_with',
    }, prev))
  }, [wsId, edgeType, setEdges])

  const onNodeDragStop = useCallback(async (_, node) => {
    if (!wsId) return
    await fetch(`/api/workspaces/${wsId}/graph/nodes/${node.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ x: node.position.x, y: node.position.y }),
    })
  }, [wsId])

  const deleteNode = async (nodeId) => {
    if (!wsId) return
    await fetch(`/api/workspaces/${wsId}/graph/nodes/${nodeId}`, { method: 'DELETE' })
    setNodes(prev => prev.filter(n => n.id !== nodeId))
    setEdges(prev => prev.filter(e => e.source !== nodeId && e.target !== nodeId))
    setSelectedNode(null)
  }

  const onNodeClick = useCallback((_, node) => setSelectedNode(node), [])

  if (!workspace) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <p>Select or create a workspace to explore the knowledge graph.</p>
      </div>
    )
  }

  return (
    <div className="h-full flex">
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeDragStop={onNodeDragStop}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
          className="bg-slate-50"
        >
          <Controls />
          <Background variant="dots" gap={16} size={1} />

          <Panel position="top-left" className="flex flex-col gap-2">
            <div className="bg-white rounded-xl shadow-lg border border-slate-200 p-3">
              <div className="flex items-center gap-2 mb-2">
                <GitBranch className="w-4 h-4 text-slate-500" />
                <span className="text-xs font-semibold text-slate-700">Knowledge Graph</span>
              </div>

              <button onClick={autoBuild} disabled={building || !results.length}
                className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs font-medium transition mb-2
                  bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:opacity-40 disabled:cursor-not-allowed border border-indigo-200">
                {building
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  : <Wand2 className="w-3.5 h-3.5" />}
                {building ? 'Building…' : results.length ? 'Auto-build from data' : 'Load data first'}
              </button>

              <div className="space-y-1.5">
                {NODE_TEMPLATES.map(t => (
                  <button key={t.type} onClick={() => addNode(t.type)}
                    className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs font-medium transition hover:opacity-80 ${t.color}`}>
                    <Plus className="w-3 h-3" />{t.label}
                  </button>
                ))}
              </div>

              <div className="mt-3 pt-3 border-t border-slate-100">
                <label className="text-[10px] text-slate-400 font-medium uppercase tracking-wider block mb-1">Edge Type</label>
                <select value={edgeType} onChange={e => setEdgeType(e.target.value)}
                  className="w-full rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-700 outline-none">
                  {EDGE_TYPES.map(t => (
                    <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
                  ))}
                </select>
              </div>
            </div>
          </Panel>
        </ReactFlow>
      </div>

      {selectedNode && (
        <aside className="w-72 border-l border-slate-200 bg-white overflow-y-auto p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-slate-800">Node Details</h3>
            <button onClick={() => deleteNode(selectedNode.id)}
              className="p-1.5 rounded-md hover:bg-red-50 transition">
              <Trash2 className="w-4 h-4 text-red-400" />
            </button>
          </div>
          <div className="space-y-3">
            <div>
              <label className="text-[10px] text-slate-400 font-medium uppercase">Type</label>
              <p className="text-xs text-slate-700 mt-0.5">{selectedNode.data?.nodeType?.replace(/_/g, ' ')}</p>
            </div>
            <div>
              <label className="text-[10px] text-slate-400 font-medium uppercase">Label</label>
              <p className="text-sm text-slate-800 font-medium mt-0.5">{selectedNode.data?.label}</p>
            </div>
            {selectedNode.data?.metadata && Object.keys(selectedNode.data.metadata).length > 0 && (
              <div>
                <label className="text-[10px] text-slate-400 font-medium uppercase">Metadata</label>
                <pre className="text-[11px] text-slate-600 mt-1 bg-slate-50 rounded-lg p-2 overflow-x-auto">
                  {JSON.stringify(selectedNode.data.metadata, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </aside>
      )}
    </div>
  )
}
