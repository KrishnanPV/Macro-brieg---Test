import { MessageSquare } from 'lucide-react'
import { interleaveSources } from '../../../lib/interleaveSources.jsx'

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
          {interleaveSources(p, newsCatalog, (seg) => highlightDataPoints(seg, i))}
        </span>
      )
    }
    return highlightDataPoints(p, i)
  })
}

function highlightDataPoints(text, baseKey) {
  const pattern = /(-?\d+[\d,]*\.?\d*\s*%|(?:SAR|USD|EUR|GBP)\s*[\d,.]+\s*(?:bn|mn|billion|million)?|\d+\.?\d*\s*(?:billion|million|mn|bn|bpd|pp|percentage points))/gi
  const parts = text.split(pattern)
  return parts.flatMap((part, i) => {
    if (i % 2 === 1) {
      return (
        <span
          key={`${baseKey}-${i}`}
          className="font-semibold text-mck-navy bg-blue-50/60 px-0.5 rounded"
          title="Data point"
        >
          {part}
        </span>
      )
    }
    return italicizeChartLabels(part, `${baseKey}-${i}`)
  })
}

/** Markdown-ish bullet body: "- ", "* ", "•", "– ", "— " */
function bulletBody(trimmed) {
  if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) return trimmed.slice(2).trim()
  if (trimmed.startsWith('• ')) return trimmed.slice(2).trim()
  if (trimmed.startsWith('•')) return trimmed.slice(1).trim()
  if (trimmed.startsWith('– ') || trimmed.startsWith('— ')) return trimmed.slice(2).trim()
  return null
}

function isContinuationLine(trimmed) {
  return /^[,;:.)\]]/.test(trimmed)
}

function renderCompactList(items, newsCatalog, keyBase) {
  const rendered = []
  let idx = 0
  while (idx < items.length) {
    const item = items[idx]
    const children = []
    let next = idx + 1
    while (next < items.length && items[next].depth > 0) {
      children.push(items[next])
      next++
    }
    rendered.push(
      <li
        key={`${keyBase}-${idx}`}
        className="border-l-2 border-slate-200/90 pl-3 -ml-px"
      >
        <div className="flex items-start gap-2">
          <span className="text-slate-400 select-none leading-snug" aria-hidden>·</span>
          <span className="text-[12.5px] leading-snug text-slate-700 min-w-0">{inlineFmt(item.text, newsCatalog)}</span>
        </div>
        {children.length > 0 && (
          <ul className="mt-1.5 space-y-1.5 list-none pl-4">
            {children.map((c, ci) => (
              <li key={ci} className="flex items-start gap-2 border-l border-slate-200/60 pl-2.5">
                <span className="text-slate-300 select-none leading-snug text-[10px]" aria-hidden>–</span>
                <span className="text-[11.5px] leading-snug text-slate-600 min-w-0">{inlineFmt(c.text, newsCatalog)}</span>
              </li>
            ))}
          </ul>
        )}
      </li>
    )
    idx = next
  }
  return rendered
}

function renderBodyList(items, newsCatalog, keyBase) {
  const rendered = []
  let idx = 0
  while (idx < items.length) {
    const item = items[idx]
    const children = []
    let next = idx + 1
    while (next < items.length && items[next].depth > 0) {
      children.push(items[next])
      next++
    }
    rendered.push(
      <li key={`${keyBase}-${idx}`} className="flex flex-col gap-1">
        <div className="flex items-start gap-2.5">
          <span className="mt-[7px] w-1.5 h-1.5 rounded-full bg-mck-deep shrink-0" />
          <span>{inlineFmt(item.text, newsCatalog)}</span>
        </div>
        {children.length > 0 && (
          <ul className="ml-6 mt-1 space-y-1">
            {children.map((c, ci) => (
              <li key={ci} className="flex items-start gap-2">
                <span className="mt-[7px] w-1 h-1 rounded-full bg-slate-400 shrink-0" />
                <span className="text-[13px]">{inlineFmt(c.text, newsCatalog)}</span>
              </li>
            ))}
          </ul>
        )}
      </li>
    )
    idx = next
  }
  return rendered
}

function parseBlocks(text, variant = 'body', newsCatalog = []) {
  const lines = text.split('\n')
  const elements = []
  let listBuf = []
  const compact = variant === 'insights'

  const flushList = () => {
    if (listBuf.length) {
      const minIndent = Math.min(...listBuf.map((item) => item.indent))
      const normalizedItems = listBuf.map((item) => ({
        ...item,
        depth: item.indent - minIndent >= 2 ? 1 : 0,
      }))
      if (compact) {
        elements.push(
          <ul key={`ul-${elements.length}`} className="space-y-3 my-0 list-none pl-0">
            {renderCompactList(normalizedItems, newsCatalog, `ul-${elements.length}`)}
          </ul>
        )
      } else {
        elements.push(
          <ul key={`ul-${elements.length}`} className="space-y-2 my-2">
            {renderBodyList(normalizedItems, newsCatalog, `ul-${elements.length}`)}
          </ul>
        )
      }
      listBuf = []
    }
  }

  for (const line of lines) {
    const trimmed = line.trim()
    const indent = line.search(/\S/)
    const normalizedIndent = indent < 0 ? 0 : indent
    const bullet = bulletBody(trimmed)

    if (trimmed.startsWith('### ')) {
      flushList()
      elements.push(<h4 key={elements.length} className="font-semibold text-slate-800 mt-4 mb-1.5 text-sm">{inlineFmt(trimmed.slice(4), newsCatalog)}</h4>)
    } else if (trimmed.startsWith('## ')) {
      flushList()
    } else if (bullet !== null && bullet !== '') {
      listBuf.push({ text: bullet, indent: normalizedIndent })
    } else if (trimmed === '') {
      flushList()
    } else if (listBuf.length > 0 && isContinuationLine(trimmed)) {
      const last = listBuf[listBuf.length - 1]
      last.text = `${last.text} ${trimmed}`.trim()
    } else {
      flushList()
      elements.push(
        <p
          key={elements.length}
          className={compact ? 'text-[12.5px] leading-snug text-slate-700' : 'leading-[1.75]'}
        >
          {inlineFmt(trimmed, newsCatalog)}
        </p>
      )
    }
  }
  flushList()
  return elements
}

export default function NarrativeBlock({ content, blockIndex, sectionIndex, onDiscuss, sectionTitle, variant = 'body', newsCatalog = [] }) {
  const compact = variant === 'insights'
  return (
    <div className="group relative">
      <div className={`${compact ? 'text-[12.5px] text-slate-700' : 'text-[13.5px] text-slate-700'} space-y-1.5`}>
        {parseBlocks(content, variant, newsCatalog)}
      </div>
      {onDiscuss && (
        <button
          onClick={() => onDiscuss(sectionIndex, sectionTitle, content)}
          className="absolute -right-2 top-0 opacity-0 group-hover:opacity-100 transition-opacity
            inline-flex items-center gap-1 px-2 py-1 text-[10px] font-medium
            text-slate-400 bg-white border border-slate-200 rounded-md shadow-sm
            hover:bg-slate-50 hover:text-mck-navy"
        >
          <MessageSquare className="w-2.5 h-2.5" />
        </button>
      )}
    </div>
  )
}
