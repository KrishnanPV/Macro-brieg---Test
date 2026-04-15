import { useState, useRef, useEffect, useLayoutEffect } from 'react'
import { createPortal } from 'react-dom'
import { ExternalLink, Library } from 'lucide-react'
import SourcesDrawer from './SourcesDrawer'

const GAP_PX = 8

/** Ancestors with scroll/auto overflow clip `position:absolute`; fixed popovers need scroll sync. */
function getScrollableAncestors(node) {
  const list = []
  let el = node?.parentElement ?? null
  while (el) {
    const st = getComputedStyle(el)
    const ox = st.overflowX
    const oy = st.overflowY
    if (/(auto|scroll|overlay)/.test(ox) || /(auto|scroll|overlay)/.test(oy)) {
      list.push(el)
    }
    el = el.parentElement
  }
  return list
}

export default function SourceChip({ n, article, catalog }) {
  const [open, setOpen] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const [popoverStyle, setPopoverStyle] = useState(null)
  const popRef = useRef(null)
  const anchorRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const fn = (e) => {
      if (anchorRef.current?.contains(e.target)) return
      if (popRef.current?.contains(e.target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', fn)
    return () => document.removeEventListener('mousedown', fn)
  }, [open])

  useLayoutEffect(() => {
    if (!open) {
      setPopoverStyle(null)
      return
    }

    const update = () => {
      const el = anchorRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const w = Math.min(window.innerWidth - 32, 288)
      let left = r.left
      left = Math.max(8, Math.min(left, window.innerWidth - w - 8))

      const estHeight = 200
      const placeBelow = r.top < estHeight + GAP_PX + 8

      if (placeBelow) {
        setPopoverStyle({
          top: r.bottom + GAP_PX,
          left,
          width: w,
          transform: 'none',
        })
      } else {
        setPopoverStyle({
          top: r.top - GAP_PX,
          left,
          width: w,
          transform: 'translateY(-100%)',
        })
      }
    }

    update()
    const scrollParents = getScrollableAncestors(anchorRef.current)
    scrollParents.forEach((node) => node.addEventListener('scroll', update, true))
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)

    return () => {
      scrollParents.forEach((node) => node.removeEventListener('scroll', update, true))
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [open])

  const title = article?.title || `Source ${n}`
  const snippet = article?.snippet || ''
  const source = article?.source || ''
  const date = article?.date || ''
  const url = article?.url || ''

  const popover =
    open &&
    popoverStyle &&
    typeof document !== 'undefined' &&
    createPortal(
      <div
        ref={popRef}
        style={{
          position: 'fixed',
          top: popoverStyle.top,
          left: popoverStyle.left,
          width: popoverStyle.width,
          transform: popoverStyle.transform,
          zIndex: 10050,
        }}
        className="rounded-lg border border-slate-200 bg-white shadow-lg p-3 text-left"
      >
        <p className="text-[11px] font-semibold text-slate-800 leading-snug line-clamp-3">{title}</p>
        {snippet && (
          <p className="text-[10px] text-slate-600 mt-1.5 leading-snug line-clamp-4">{snippet}</p>
        )}
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 mt-2 text-[9px] text-slate-400">
          {source && <span>{source}</span>}
          {date && <span>{date}</span>}
        </div>
        <div className="flex flex-wrap gap-2 mt-2.5 pt-2 border-t border-slate-100">
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[10px] font-medium text-mck-deep hover:underline inline-flex items-center gap-0.5"
              onClick={(e) => e.stopPropagation()}
            >
              Open article <ExternalLink className="w-3 h-3" />
            </a>
          )}
          {catalog?.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setShowAll(true)
                setOpen(false)
              }}
              className="text-[10px] font-medium text-slate-500 hover:text-slate-800 inline-flex items-center gap-0.5"
            >
              All sources <Library className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>,
      document.body
    )

  return (
    <>
      <span ref={anchorRef} className="relative inline-flex align-super ml-0.5 translate-y-0.5">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-center justify-center min-w-[1.125rem] h-4 px-0.5 rounded-full bg-slate-200/90 text-[9px] font-semibold text-slate-600 hover:bg-slate-300/90 transition"
          aria-expanded={open}
          aria-label={`Source ${n}`}
        >
          {n}
        </button>
      </span>
      {popover}
      {showAll && (
        <SourcesDrawer catalog={catalog} highlightIndex={n} onClose={() => setShowAll(false)} />
      )}
    </>
  )
}
