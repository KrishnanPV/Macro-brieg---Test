import { BarChart3, Trash2 } from 'lucide-react'

export default function DataCell({ cell, onUpdate, onDelete }) {
  return (
    <div className="group rounded-xl border border-blue-200 bg-white shadow-sm overflow-hidden hover:border-blue-300 transition">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-blue-100 bg-blue-50/50">
        <BarChart3 className="w-3.5 h-3.5 text-blue-500" />
        <span className="text-[10px] font-medium text-blue-500 uppercase tracking-wider">Data View</span>
        <div className="flex-1" />
        <button onClick={() => onDelete(cell.id)}
          className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 transition">
          <Trash2 className="w-3 h-3 text-red-400" />
        </button>
      </div>
      <div className="px-4 py-6 text-center">
        <p className="text-sm text-slate-400">Embed a KPI chart here by selecting data from the Dashboard.</p>
        <p className="text-xs text-slate-300 mt-1">Data cells will render interactive charts from your loaded KPI data.</p>
      </div>
    </div>
  )
}
