import { useState, useRef, useEffect } from 'react'
import { FileText, Trash2, Check } from 'lucide-react'

export default function MarkdownCell({ cell, onUpdate, onDelete }) {
  const [editing, setEditing] = useState(!cell.content)
  const [content, setContent] = useState(cell.content || '')
  const textareaRef = useRef(null)

  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus()
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px'
    }
  }, [editing])

  const save = () => {
    onUpdate(cell.id, content)
    setEditing(false)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      setContent(cell.content || '')
      setEditing(false)
    }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save()
  }

  return (
    <div className="group rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden hover:border-slate-300 transition">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-100 bg-slate-50/50">
        <FileText className="w-3.5 h-3.5 text-slate-400" />
        <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">Note</span>
        <div className="flex-1" />
        <button onClick={() => onDelete(cell.id)}
          className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 transition">
          <Trash2 className="w-3 h-3 text-red-400" />
        </button>
      </div>
      <div className="px-4 py-3">
        {editing ? (
          <div>
            <textarea
              ref={textareaRef}
              value={content}
              onChange={e => {
                setContent(e.target.value)
                e.target.style.height = 'auto'
                e.target.style.height = e.target.scrollHeight + 'px'
              }}
              onKeyDown={handleKeyDown}
              placeholder="Write your notes here… (Ctrl+Enter to save)"
              className="w-full min-h-[60px] text-sm text-slate-700 leading-relaxed resize-none outline-none placeholder:text-slate-300"
            />
            <div className="flex justify-end mt-2">
              <button onClick={save} className="inline-flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white text-xs rounded-md hover:bg-blue-700 transition">
                <Check className="w-3 h-3" /> Save
              </button>
            </div>
          </div>
        ) : (
          <div onClick={() => setEditing(true)} className="cursor-text min-h-[40px]">
            {content ? (
              <div className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{content}</div>
            ) : (
              <p className="text-sm text-slate-300 italic">Click to add notes…</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
