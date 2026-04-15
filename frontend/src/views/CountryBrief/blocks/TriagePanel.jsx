import { useState } from 'react'
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, BarChart3 } from 'lucide-react'

export default function TriagePanel({ triageResults = [] }) {
  const [open, setOpen] = useState(false)

  if (!triageResults.length) return null

  const notable = triageResults.filter(t => t.notable)
  const skipped = triageResults.filter(t => !t.notable)

  return (
    <div className="max-w-4xl mx-auto px-6 mb-4">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-2 text-[11px] font-medium text-slate-400 hover:text-slate-600 transition"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <BarChart3 className="w-3 h-3" />
        {notable.length} KPIs selected · {skipped.length} filtered out
      </button>

      {open && (
        <div className="mt-2 rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="divide-y divide-slate-100">
            {triageResults.map((t) => (
              <div key={t.kpi_id} className="flex items-center gap-3 px-4 py-2.5">
                {t.notable ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                ) : (
                  <XCircle className="w-3.5 h-3.5 text-slate-300 shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-medium ${t.notable ? 'text-slate-700' : 'text-slate-400'}`}>
                      KPI {t.kpi_id}: {t.kpi_name}
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">
                      score: {t.score}
                    </span>
                  </div>
                  {t.reasons?.length > 0 && (
                    <p className="text-[10px] text-slate-400 mt-0.5 truncate">
                      {t.reasons.join(' · ')}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
