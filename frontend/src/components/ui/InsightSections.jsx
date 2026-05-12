import { AlertTriangle, FileText, Search, Zap } from 'lucide-react'
import { interleaveSources } from '../../lib/interleaveSources.jsx'

const CHART_LABEL_TOKEN_RE = /(\b\d+[A-Z]\b)/g
const CHART_LABEL_ONLY_RE = /^\d+[A-Z]$/

function italicizeChartLabels(text, keyPrefix = 'lbl') {
  if (!text) return text
  const parts = String(text).split(CHART_LABEL_TOKEN_RE)
  if (parts.length === 1) return text
  return parts.map((part, i) => (
    CHART_LABEL_ONLY_RE.test(part)
      ? <em key={`${keyPrefix}-${i}`} className="italic">{part}</em>
      : part
  ))
}

function inlineFmt(s, newsCatalog) {
  const parts = s.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) {
      return <strong key={i} className="font-semibold text-slate-800">{p.slice(2, -2)}</strong>
    }
    if (newsCatalog?.length) {
      return (
        <span key={i}>
          {interleaveSources(p, newsCatalog, (seg) => italicizeChartLabels(seg, `src-${i}`))}
        </span>
      )
    }
    return italicizeChartLabels(p, `txt-${i}`)
  })
}

function parseMarkdownBlocks(text, newsCatalog) {
  const lines = text.split('\n')
  const elements = []
  let listBuf = []

  const flushList = () => {
    if (listBuf.length) {
      elements.push(
        <ul key={`ul-${elements.length}`} className="space-y-1.5 mb-2">
          {listBuf.map((l, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-mck-deep shrink-0" />
              <span>{inlineFmt(l, newsCatalog)}</span>
            </li>
          ))}
        </ul>
      )
      listBuf = []
    }
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('### ')) {
      flushList()
      elements.push(<h4 key={elements.length} className="font-semibold text-slate-800 mt-3 mb-1.5 text-xs">{inlineFmt(trimmed.slice(4), newsCatalog)}</h4>)
    } else if (trimmed.startsWith('## ')) {
      flushList()
    } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      listBuf.push(trimmed.slice(2))
    } else if (trimmed === '') {
      flushList()
    } else {
      flushList()
      elements.push(<p key={elements.length} className="mb-2 leading-relaxed">{inlineFmt(trimmed, newsCatalog)}</p>)
    }
  }
  flushList()
  return elements
}

function splitSections(text) {
  const sectionPattern = /^## (.+)$/gm
  const sections = []
  let lastIdx = 0
  let lastTitle = null
  let match

  while ((match = sectionPattern.exec(text)) !== null) {
    if (lastTitle !== null) {
      sections.push({ title: lastTitle, body: text.slice(lastIdx, match.index).trim() })
    }
    lastTitle = match[1].trim()
    lastIdx = match.index + match[0].length
  }
  if (lastTitle !== null) {
    sections.push({ title: lastTitle, body: text.slice(lastIdx).trim() })
  }

  if (sections.length === 0) {
    return { summary: null, findings: null, implications: null, fallback: text }
  }

  let summary = null, findings = null, implications = null
  for (const s of sections) {
    const lower = s.title.toLowerCase()
    if (lower.includes('summary')) summary = s.body
    else if (lower.includes('key findings') || lower.includes('findings')) findings = s.body
    else if (lower.includes('implications') || lower.includes('inference')) implications = s.body
  }

  return { summary, findings, implications, fallback: null }
}

export default function InsightSections({ text, newsCatalog = [] }) {
  const { summary, findings, implications, fallback } = splitSections(text)

  if (fallback) {
    return <div className="text-[13px] text-slate-700 leading-relaxed">{parseMarkdownBlocks(fallback, newsCatalog)}</div>
  }

  if (!summary && !findings && !implications) {
    return <div className="text-[13px] text-slate-700 leading-relaxed">{parseMarkdownBlocks(text, newsCatalog)}</div>
  }

  return (
    <div className="space-y-4">
      {summary && (
        <div className="rounded-xl bg-gradient-to-br from-slate-50 to-mck-blue/5 border border-slate-200/80 px-5 py-4">
          <div className="flex items-center gap-2 mb-2">
            <FileText className="w-3.5 h-3.5 text-mck-deep" />
            <h4 className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Summary</h4>
          </div>
          <p className="text-[13px] font-medium text-slate-800 leading-relaxed">{inlineFmt(summary, newsCatalog)}</p>
        </div>
      )}
      {findings && (
        <div className="border-l-[3px] border-mck-deep pl-5 py-1">
          <div className="flex items-center gap-2 mb-2.5">
            <Search className="w-3.5 h-3.5 text-mck-deep" />
            <h4 className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Key Findings</h4>
          </div>
          <div className="text-[13px] text-slate-700 leading-relaxed">{parseMarkdownBlocks(findings, newsCatalog)}</div>
        </div>
      )}
      {implications && (
        <div>
          <div className="border-l-[3px] border-amber-400 bg-gradient-to-br from-amber-50/50 to-orange-50/20 rounded-r-xl pl-5 pr-5 py-4">
            <div className="flex items-center gap-2 mb-2.5">
              <Zap className="w-3.5 h-3.5 text-amber-600" />
              <h4 className="text-[11px] font-semibold text-amber-700 uppercase tracking-wider">Implications</h4>
            </div>
            <div className="text-[13px] text-slate-700 leading-relaxed">{parseMarkdownBlocks(implications, newsCatalog)}</div>
          </div>
          <div className="flex items-start gap-2 mt-2.5 px-1">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-0.5" />
            <p className="text-[10px] text-amber-600/80 leading-snug italic">
              Implications are AI-generated inferences combining data with macroeconomic knowledge. Validate independently.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

export { parseMarkdownBlocks, inlineFmt }
