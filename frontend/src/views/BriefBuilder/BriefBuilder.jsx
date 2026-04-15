import { useState, useEffect } from 'react'
import { FileText, Plus, Download, Trash2, Save, Sparkles } from 'lucide-react'
import useWorkspaceStore from '../../stores/workspaceStore'

const TEMPLATES = [
  { id: 'country_overview', name: 'Country Overview', description: 'Comprehensive macro overview of a single country' },
  { id: 'comparative', name: 'Comparative Analysis', description: 'Side-by-side comparison of multiple economies' },
  { id: 'thematic', name: 'Thematic Deep-Dive', description: 'Focused analysis on a specific macro theme' },
]

export default function BriefBuilder() {
  const workspace = useWorkspaceStore(s => s.activeWorkspace)
  const [briefs, setBriefs] = useState([])
  const [activeBrief, setActiveBrief] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [loading, setLoading] = useState(false)

  const wsId = workspace?.id

  useEffect(() => {
    if (!wsId) return
    fetch(`/api/workspaces/${wsId}/briefs`).then(r => r.json()).then(setBriefs)
  }, [wsId])

  const createBrief = async (title, template) => {
    const defaultSections = template === 'country_overview'
      ? [
          { title: 'Executive Summary', text: '', bullets: [] },
          { title: 'GDP & Growth', text: '', bullets: [] },
          { title: 'Trade & Investment', text: '', bullets: [] },
          { title: 'Inflation & Monetary Policy', text: '', bullets: [] },
          { title: 'Key Risks & Outlook', text: '', bullets: [] },
        ]
      : template === 'comparative'
      ? [
          { title: 'Overview', text: '', bullets: [] },
          { title: 'Growth Comparison', text: '', bullets: [] },
          { title: 'Structural Differences', text: '', bullets: [] },
          { title: 'Outlook', text: '', bullets: [] },
        ]
      : [
          { title: 'Theme Introduction', text: '', bullets: [] },
          { title: 'Data Analysis', text: '', bullets: [] },
          { title: 'Implications', text: '', bullets: [] },
        ]

    const resp = await fetch(`/api/workspaces/${wsId}/briefs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, template, content: { sections: defaultSections } }),
    })
    const brief = await resp.json()
    setBriefs(prev => [brief, ...prev])
    setActiveBrief(brief)
    setShowCreate(false)
  }

  const updateSection = async (sectionIdx, field, value) => {
    if (!activeBrief) return
    const content = { ...activeBrief.content }
    const sections = [...content.sections]
    sections[sectionIdx] = { ...sections[sectionIdx], [field]: value }
    content.sections = sections

    const resp = await fetch(`/api/workspaces/${wsId}/briefs/${activeBrief.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
    const updated = await resp.json()
    setActiveBrief(updated)
    setBriefs(prev => prev.map(b => b.id === updated.id ? updated : b))
  }

  const exportBrief = async (fmt) => {
    if (!activeBrief) return
    const url = `/api/workspaces/${wsId}/briefs/${activeBrief.id}/export/${fmt}`
    const resp = await fetch(url)
    const blob = await resp.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${activeBrief.title.replace(/\s+/g, '_')}.${fmt}`
    a.click()
  }

  const deleteBrief = async (id) => {
    await fetch(`/api/workspaces/${wsId}/briefs/${id}`, { method: 'DELETE' })
    setBriefs(prev => prev.filter(b => b.id !== id))
    if (activeBrief?.id === id) setActiveBrief(null)
  }

  if (!workspace) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <p>Select a workspace to build briefs.</p>
      </div>
    )
  }

  return (
    <div className="flex h-full">
      {/* Brief list sidebar */}
      <aside className="w-64 shrink-0 border-r border-slate-200 bg-white overflow-y-auto">
        <div className="px-4 py-4 border-b border-slate-100">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Briefs</h3>
            <button onClick={() => setShowCreate(!showCreate)}
              className="p-1.5 rounded-md hover:bg-slate-100 transition">
              <Plus className="w-3.5 h-3.5 text-slate-500" />
            </button>
          </div>

          {showCreate && (
            <div className="space-y-2 mb-3">
              {TEMPLATES.map(t => (
                <button key={t.id} onClick={() => {
                  const title = window.prompt('Brief title:', t.name)
                  if (title) createBrief(title, t.id)
                }}
                  className="w-full text-left rounded-lg border border-slate-100 p-2.5 hover:border-blue-300 transition">
                  <p className="text-xs font-medium text-slate-700">{t.name}</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">{t.description}</p>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="px-3 py-2 space-y-1">
          {briefs.map(brief => (
            <div key={brief.id}
              onClick={() => setActiveBrief(brief)}
              className={`group flex items-center justify-between rounded-lg px-3 py-2.5 cursor-pointer transition
                ${activeBrief?.id === brief.id ? 'bg-blue-50 border border-blue-200' : 'hover:bg-slate-50'}`}>
              <div className="min-w-0">
                <p className="text-xs font-medium text-slate-700 truncate">{brief.title}</p>
                <p className="text-[10px] text-slate-400">{brief.template.replace(/_/g, ' ')}</p>
              </div>
              <button onClick={e => { e.stopPropagation(); deleteBrief(brief.id) }}
                className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50">
                <Trash2 className="w-3 h-3 text-red-400" />
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* Editor */}
      <div className="flex-1 overflow-y-auto p-6">
        {!activeBrief ? (
          <div className="flex items-center justify-center h-full text-slate-400">
            <div className="text-center">
              <FileText className="w-12 h-12 text-slate-200 mx-auto mb-4" />
              <p className="text-sm">Select or create a brief to start composing.</p>
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-slate-800">{activeBrief.title}</h2>
              <div className="flex items-center gap-2">
                <button onClick={() => exportBrief('pptx')}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium text-slate-600 hover:bg-slate-50 transition">
                  <Download className="w-3.5 h-3.5" /> PPTX
                </button>
                <button onClick={() => exportBrief('markdown')}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium text-slate-600 hover:bg-slate-50 transition">
                  <Download className="w-3.5 h-3.5" /> Markdown
                </button>
              </div>
            </div>

            <div className="space-y-6">
              {activeBrief.content?.sections?.map((section, idx) => (
                <SectionEditor key={idx} section={section} index={idx} onUpdate={updateSection} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function SectionEditor({ section, index, onUpdate }) {
  const [editingText, setEditingText] = useState(false)
  const [text, setText] = useState(section.text || '')
  const [newBullet, setNewBullet] = useState('')

  const saveText = () => {
    onUpdate(index, 'text', text)
    setEditingText(false)
  }

  const addBullet = () => {
    if (!newBullet.trim()) return
    onUpdate(index, 'bullets', [...(section.bullets || []), newBullet.trim()])
    setNewBullet('')
  }

  const removeBullet = (bulletIdx) => {
    onUpdate(index, 'bullets', section.bullets.filter((_, i) => i !== bulletIdx))
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      <div className="px-5 py-3 bg-slate-50 border-b border-slate-100">
        <h3 className="text-sm font-semibold text-slate-700">{section.title}</h3>
      </div>
      <div className="px-5 py-4 space-y-3">
        {editingText ? (
          <div>
            <textarea value={text} onChange={e => setText(e.target.value)} rows={4}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 outline-none focus:border-blue-400 resize-none" />
            <button onClick={saveText} className="mt-2 px-3 py-1.5 bg-blue-600 text-white text-xs rounded-md">
              <Save className="w-3 h-3 inline mr-1" /> Save
            </button>
          </div>
        ) : (
          <div onClick={() => setEditingText(true)} className="cursor-text min-h-[32px]">
            {section.text ? (
              <p className="text-sm text-slate-700 leading-relaxed">{section.text}</p>
            ) : (
              <p className="text-sm text-slate-300 italic">Click to add section text…</p>
            )}
          </div>
        )}

        {section.bullets?.length > 0 && (
          <ul className="list-disc pl-5 space-y-1">
            {section.bullets.map((b, i) => (
              <li key={i} className="text-xs text-slate-600 group">
                {b}
                <button onClick={() => removeBullet(i)}
                  className="ml-2 text-red-400 opacity-0 group-hover:opacity-100 transition text-[10px]">remove</button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex gap-2">
          <input value={newBullet} onChange={e => setNewBullet(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addBullet()}
            placeholder="Add a bullet point…"
            className="flex-1 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs outline-none focus:border-blue-400" />
          <button onClick={addBullet} className="px-3 py-1.5 bg-slate-100 text-slate-600 text-xs rounded-md hover:bg-slate-200">Add</button>
        </div>
      </div>
    </div>
  )
}
