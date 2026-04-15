import { Lightbulb, Trash2, Pin } from 'lucide-react'
import InsightSections from '../../../components/ui/InsightSections'

export default function InsightCell({ cell, onUpdate, onDelete }) {
  return (
    <div className="group rounded-xl border border-purple-200 bg-white shadow-sm overflow-hidden hover:border-purple-300 transition">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-purple-100 bg-purple-50/50">
        <Lightbulb className="w-3.5 h-3.5 text-purple-500" />
        <span className="text-[10px] font-medium text-purple-500 uppercase tracking-wider">Pinned Insight</span>
        <Pin className="w-3 h-3 text-purple-400" />
        <div className="flex-1" />
        <button onClick={() => onDelete(cell.id)}
          className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 transition">
          <Trash2 className="w-3 h-3 text-red-400" />
        </button>
      </div>
      <div className="px-4 py-3">
        {cell.content ? (
          <InsightSections text={cell.content} />
        ) : (
          <p className="text-sm text-slate-300 italic">No insight content yet.</p>
        )}
      </div>
    </div>
  )
}
