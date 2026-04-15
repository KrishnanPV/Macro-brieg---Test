import { MessageSquare } from 'lucide-react'
import { interleaveSources } from '../../../lib/interleaveSources.jsx'

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
  return parts.map((part, i) => {
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
    return part
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

function parseBlocks(text, variant = 'body', newsCatalog = []) {
  const lines = text.split('\n')
  const elements = []
  let listBuf = []
  const compact = variant === 'insights'

  const flushList = () => {
    if (listBuf.length) {
      if (compact) {
        elements.push(
          <ul key={`ul-${elements.length}`} className="space-y-3 my-0 list-none pl-0">
            {listBuf.map((l, i) => (
              <li
                key={i}
                className="flex items-start gap-2 border-l-2 border-slate-200/90 pl-3 -ml-px"
              >
                <span className="text-slate-400 select-none leading-snug" aria-hidden>·</span>
                <span className="text-[12.5px] leading-snug text-slate-700 min-w-0">{inlineFmt(l, newsCatalog)}</span>
              </li>
            ))}
          </ul>
        )
      } else {
        elements.push(
          <ul key={`ul-${elements.length}`} className="space-y-2 my-2">
            {listBuf.map((l, i) => (
              <li key={i} className="flex items-start gap-2.5">
                <span className="mt-[7px] w-1.5 h-1.5 rounded-full bg-mck-deep shrink-0" />
                <span>{inlineFmt(l, newsCatalog)}</span>
              </li>
            ))}
          </ul>
        )
      }
      listBuf = []
    }
  }

  for (const line of lines) {
    const trimmed = line.trim()
    const bullet = bulletBody(trimmed)

    if (trimmed.startsWith('### ')) {
      flushList()
      elements.push(<h4 key={elements.length} className="font-semibold text-slate-800 mt-4 mb-1.5 text-sm">{inlineFmt(trimmed.slice(4), newsCatalog)}</h4>)
    } else if (trimmed.startsWith('## ')) {
      flushList()
    } else if (bullet !== null && bullet !== '') {
      listBuf.push(bullet)
    } else if (trimmed === '') {
      flushList()
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
