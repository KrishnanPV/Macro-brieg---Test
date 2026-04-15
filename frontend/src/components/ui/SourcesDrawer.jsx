import { useEffect, useRef } from 'react'
import { X, ExternalLink } from 'lucide-react'

export default function SourcesDrawer({ catalog, highlightIndex, onClose }) {
  const hiRef = useRef(null)

  useEffect(() => {
    hiRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [highlightIndex, catalog])

  if (!catalog?.length) return null

  return (
    <div className="fixed inset-0 z-[100] flex justify-end">
      <button
        type="button"
        className="absolute inset-0 bg-black/20"
        onClick={onClose}
        aria-label="Close sources"
      />
      <aside className="relative w-full max-w-md h-full bg-white shadow-xl border-l border-slate-200 flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 shrink-0">
          <h3 className="text-sm font-semibold text-slate-800">Sources</h3>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-500"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {catalog.map((a) => {
            const isHi = a.index === highlightIndex
            return (
              <div
                key={a.id || `idx-${a.index}`}
                ref={isHi ? hiRef : undefined}
                className={`rounded-lg border p-3 transition-colors ${
                  isHi ? 'border-mck-deep bg-blue-50/60 ring-1 ring-mck-deep/20' : 'border-slate-100 bg-white'
                }`}
              >
                <div className="flex items-start gap-2">
                  <span className="inline-flex items-center justify-center min-w-[1.25rem] h-5 rounded-full bg-slate-100 text-[10px] font-bold text-slate-600 shrink-0">
                    {a.index}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[12px] font-semibold text-slate-800 leading-snug">{a.title || 'Untitled'}</p>
                    {a.snippet && (
                      <p className="text-[11px] text-slate-600 mt-1.5 leading-snug line-clamp-4">{a.snippet}</p>
                    )}
                    <div className="flex flex-wrap gap-x-2 gap-y-0.5 mt-2 text-[10px] text-slate-400">
                      {a.source && <span>{a.source}</span>}
                      {a.date && <span>{a.date}</span>}
                    </div>
                    {a.url && (
                      <a
                        href={a.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 mt-2 text-[11px] font-medium text-mck-deep hover:underline"
                      >
                        Open article <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </aside>
    </div>
  )
}
