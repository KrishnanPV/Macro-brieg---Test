import { FileSearch, Trash2, ExternalLink } from 'lucide-react'

export default function SourceCell({ cell, onUpdate, onDelete }) {
  const meta = cell.metadata || {}

  return (
    <div className="group rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden hover:border-gray-300 transition">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-100 bg-gray-50/50">
        <FileSearch className="w-3.5 h-3.5 text-gray-500" />
        <span className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Source Document</span>
        {meta.source_url && (
          <a href={meta.source_url} target="_blank" rel="noopener noreferrer" className="ml-auto">
            <ExternalLink className="w-3 h-3 text-blue-400 hover:text-blue-600" />
          </a>
        )}
        <div className="flex-1" />
        <button onClick={() => onDelete(cell.id)}
          className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 transition">
          <Trash2 className="w-3 h-3 text-red-400" />
        </button>
      </div>
      <div className="px-4 py-3">
        {meta.title && <h4 className="text-sm font-medium text-slate-700 mb-1">{meta.title}</h4>}
        <div className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap max-h-60 overflow-y-auto">
          {cell.content || 'No content.'}
        </div>
      </div>
    </div>
  )
}
