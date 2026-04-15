import { useState, useEffect, useRef } from 'react'
import { Plus, Send, FileText, Brain, BookOpen, Upload, Trash2, GripVertical } from 'lucide-react'
import useWorkspaceStore from '../../stores/workspaceStore'
import MarkdownCell from './cells/MarkdownCell'
import AICell from './cells/AICell'
import DataCell from './cells/DataCell'
import InsightCell from './cells/InsightCell'
import SourceCell from './cells/SourceCell'

const CELL_TYPES = [
  { type: 'markdown', label: 'Note', icon: FileText, color: 'text-slate-600' },
  { type: 'ai', label: 'AI Chat', icon: Brain, color: 'text-indigo-600' },
  { type: 'data', label: 'Data View', icon: BookOpen, color: 'text-blue-600' },
]

export default function Notebook() {
  const workspace = useWorkspaceStore(s => s.activeWorkspace)
  const [cells, setCells] = useState([])
  const [loading, setLoading] = useState(false)
  const [showAddMenu, setShowAddMenu] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
  const [documents, setDocuments] = useState([])

  const wsId = workspace?.id

  useEffect(() => {
    if (!wsId) return
    setLoading(true)
    Promise.all([
      fetch(`/api/workspaces/${wsId}/cells`).then(r => r.json()),
      fetch(`/api/workspaces/${wsId}/documents`).then(r => r.json()),
    ]).then(([cellData, docData]) => {
      setCells(cellData)
      setDocuments(docData)
    }).finally(() => setLoading(false))
  }, [wsId])

  const addCell = async (type) => {
    if (!wsId) return
    const resp = await fetch(`/api/workspaces/${wsId}/cells`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cell_type: type, content: '' }),
    })
    const cell = await resp.json()
    setCells(prev => [...prev, cell])
    setShowAddMenu(false)
  }

  const updateCell = async (cellId, content, metadata) => {
    const body = {}
    if (content !== undefined) body.content = content
    if (metadata !== undefined) body.metadata = metadata
    await fetch(`/api/workspaces/${wsId}/cells/${cellId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    setCells(prev => prev.map(c => c.id === cellId ? { ...c, ...body } : c))
  }

  const deleteCell = async (cellId) => {
    await fetch(`/api/workspaces/${wsId}/cells/${cellId}`, { method: 'DELETE' })
    setCells(prev => prev.filter(c => c.id !== cellId))
  }

  const uploadDocument = async (title, content) => {
    const resp = await fetch(`/api/workspaces/${wsId}/documents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, content, doc_type: 'text' }),
    })
    const doc = await resp.json()
    setDocuments(prev => [doc, ...prev])
  }

  const deleteDocument = async (docId) => {
    await fetch(`/api/workspaces/${wsId}/documents/${docId}`, { method: 'DELETE' })
    setDocuments(prev => prev.filter(d => d.id !== docId))
  }

  if (!workspace) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <p>Select or create a workspace to begin your research.</p>
      </div>
    )
  }

  const renderCell = (cell) => {
    const props = { key: cell.id, cell, onUpdate: updateCell, onDelete: deleteCell, workspace }
    switch (cell.cell_type) {
      case 'markdown': return <MarkdownCell {...props} />
      case 'ai': return <AICell {...props} />
      case 'data': return <DataCell {...props} />
      case 'insight': return <InsightCell {...props} />
      case 'source': return <SourceCell {...props} />
      default: return <MarkdownCell {...props} />
    }
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto">
          <div className="mb-6">
            <h2 className="text-lg font-bold text-slate-800">{workspace.name}</h2>
            <p className="text-xs text-slate-500 mt-1">{workspace.description || 'Research notebook'}</p>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <span className="inline-block h-4 w-4 rounded-full border-2 border-slate-300 border-t-transparent animate-spin" />
              Loading notebook…
            </div>
          ) : (
            <div className="space-y-3">
              {cells.map(cell => renderCell(cell))}

              <div className="relative">
                <button onClick={() => setShowAddMenu(!showAddMenu)}
                  className="w-full border-2 border-dashed border-slate-200 rounded-xl py-3 text-sm text-slate-400 hover:border-blue-300 hover:text-blue-500 transition flex items-center justify-center gap-2">
                  <Plus className="w-4 h-4" /> Add Cell
                </button>
                {showAddMenu && (
                  <div className="absolute top-full left-1/2 -translate-x-1/2 mt-2 bg-white rounded-xl shadow-lg border border-slate-200 p-2 z-10 flex gap-1">
                    {CELL_TYPES.map(({ type, label, icon: Icon, color }) => (
                      <button key={type} onClick={() => addCell(type)}
                        className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-50 transition text-sm">
                        <Icon className={`w-4 h-4 ${color}`} />{label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Context sidebar */}
      <aside className="w-72 shrink-0 border-l border-slate-200 bg-white overflow-y-auto">
        <div className="px-4 py-4 border-b border-slate-100">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Context Sources</h3>
            <button onClick={() => setShowUpload(!showUpload)}
              className="p-1.5 rounded-md hover:bg-slate-100 transition">
              <Upload className="w-3.5 h-3.5 text-slate-500" />
            </button>
          </div>

          {showUpload && (
            <UploadPanel onUpload={uploadDocument} onClose={() => setShowUpload(false)} />
          )}
        </div>

        <div className="px-4 py-3 space-y-2">
          {documents.length === 0 ? (
            <p className="text-xs text-slate-400 italic">No documents added yet. Upload text or paste content to give the AI extra context.</p>
          ) : documents.map(doc => (
            <div key={doc.id} className="group rounded-lg border border-slate-100 p-3 hover:border-slate-200 transition">
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <p className="text-xs font-medium text-slate-700 truncate">{doc.title}</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">{doc.doc_type} · {new Date(doc.created_at).toLocaleDateString()}</p>
                </div>
                <button onClick={() => deleteDocument(doc.id)}
                  className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 transition">
                  <Trash2 className="w-3 h-3 text-red-400" />
                </button>
              </div>
              <p className="text-[11px] text-slate-500 mt-1.5 line-clamp-2">{doc.content}</p>
            </div>
          ))}
        </div>
      </aside>
    </div>
  )
}

function UploadPanel({ onUpload, onClose }) {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')

  const handleSubmit = () => {
    if (!title.trim() || !content.trim()) return
    onUpload(title, content)
    setTitle('')
    setContent('')
    onClose()
  }

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-3 space-y-2">
      <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Document title"
        className="w-full rounded-md border border-slate-200 px-2.5 py-1.5 text-xs focus:border-blue-400 outline-none" />
      <textarea value={content} onChange={e => setContent(e.target.value)} placeholder="Paste content here…"
        rows={4} className="w-full rounded-md border border-slate-200 px-2.5 py-1.5 text-xs focus:border-blue-400 outline-none resize-none" />
      <div className="flex gap-2">
        <button onClick={handleSubmit} className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded-md hover:bg-blue-700 transition">Add</button>
        <button onClick={onClose} className="px-3 py-1.5 text-xs text-slate-500 hover:text-slate-700 transition">Cancel</button>
      </div>
    </div>
  )
}
