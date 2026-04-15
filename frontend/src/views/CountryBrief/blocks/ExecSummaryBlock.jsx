import { FileText, MessageSquare } from 'lucide-react'
import { parseMarkdownBlocks } from '../../../components/ui/InsightSections'

export default function ExecSummaryBlock({ content, blockIndex, onDiscuss, newsCatalog = [] }) {
  return (
    <div className="group relative rounded-2xl bg-gradient-to-br from-slate-50 via-blue-50/30 to-indigo-50/20 border border-slate-200/80 shadow-sm overflow-hidden">
      <div className="px-6 py-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-mck-navy/10 flex items-center justify-center">
              <FileText className="w-4 h-4 text-mck-navy" />
            </div>
            <h2 className="text-sm font-bold text-mck-navy uppercase tracking-wider">
              Executive Summary
            </h2>
          </div>
          {onDiscuss && (
            <button
              onClick={() => onDiscuss(blockIndex, 'Executive Summary', content)}
              className="opacity-0 group-hover:opacity-100 transition-opacity inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-slate-500 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:text-mck-navy"
            >
              <MessageSquare className="w-3 h-3" />Discuss
            </button>
          )}
        </div>
        <div className="text-[14px] text-slate-700 leading-relaxed space-y-2">
          {parseMarkdownBlocks(content, newsCatalog)}
        </div>
      </div>
    </div>
  )
}
