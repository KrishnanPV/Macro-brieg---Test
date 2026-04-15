import { useState, useRef, useLayoutEffect } from 'react'
import { createPortal } from 'react-dom'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

const GAP_PX = 8

/** Scroll/overflow ancestors that clip `position:absolute` children; need listeners for fixed popover sync. */
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

const POLARITY_BY_KPI = {
  '1': 'higher_is_better',
  '2': 'higher_is_better',
  '3': 'higher_is_better',
  '4': 'higher_is_better',
  '5': 'lower_is_better',
  '6': 'higher_is_better',
  '7': 'lower_is_better',
  '8': 'lower_is_better',
  '9': 'neutral',
}

function polarityFromLabel(label) {
  const L = (label || '').toLowerCase()
  if (/unemployment|jobless/.test(L)) return 'lower_is_better'
  if (/external debt|debt.*gdp|debt.*%/.test(L)) return 'lower_is_better'
  if (/inflation|cpi|consumer price/.test(L)) return 'lower_is_better'
  if (/population/.test(L)) return 'neutral'
  return 'higher_is_better'
}

function polarity(kpiId, label) {
  return (kpiId && POLARITY_BY_KPI[kpiId]) || polarityFromLabel(label)
}

function trendIcon(trend) {
  if (trend === 'up') return TrendingUp
  if (trend === 'down') return TrendingDown
  return Minus
}

function ribbonStyles(kpiId, trend, label) {
  const pol = polarity(kpiId, label)
  const Icon = trendIcon(trend)

  if (pol === 'neutral' || trend === 'flat') {
    return { Icon: trend === 'flat' ? Minus : Icon, valueClass: 'text-slate-700', iconClass: 'text-slate-400' }
  }

  const good = pol === 'lower_is_better' ? trend === 'down' : trend === 'up'

  if (good) {
    return { Icon, valueClass: 'text-emerald-600', iconClass: 'text-emerald-500' }
  }
  return { Icon, valueClass: 'text-red-600', iconClass: 'text-red-500' }
}

function formatChangePct(cp) {
  if (cp == null) return null
  const sign = cp > 0 ? '+' : ''
  return `${sign}${cp.toFixed(1)}%`
}

function MetricPopover({ metric, fixedPosition, onPopoverEnter, onPopoverLeave }) {
  const hasPrior = metric.prior_value != null
  const hasCagr = metric.cagr != null
  const hasEarliest = metric.earliest_value != null

  if (!hasPrior && !hasCagr) return null

  const { top, left } = fixedPosition

  return (
    <div
      role="tooltip"
      style={{
        position: 'fixed',
        top,
        left,
        transform: 'translateX(-50%)',
      }}
      className="z-[10050] w-56 max-w-[calc(100vw-1.5rem)]
        bg-white rounded-xl shadow-xl border border-slate-200 p-3.5 text-xs
        animate-in fade-in slide-in-from-top-1 duration-150"
      onMouseEnter={onPopoverEnter}
      onMouseLeave={onPopoverLeave}
    >
      <div className="absolute -top-1.5 left-1/2 -translate-x-1/2 w-3 h-3 bg-white border-l border-t border-slate-200 rotate-45" />

      <p className="font-semibold text-slate-800 text-[12px] mb-2">{metric.label}</p>

      <div className="space-y-1.5">
        {hasPrior && (
          <div className="flex justify-between">
            <span className="text-slate-400">Prior ({metric.prior_label})</span>
            <span className="font-medium text-slate-600">{metric.prior_value}</span>
          </div>
        )}

        {hasCagr && hasEarliest && (
          <>
            <div className="border-t border-slate-100 my-1" />
            <div className="flex justify-between">
              <span className="text-slate-400">From {metric.earliest_label}</span>
              <span className="font-medium text-slate-600">{metric.earliest_value}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">CAGR</span>
              <span className="font-semibold text-slate-700">{formatChangePct(metric.cagr)}</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function MetricCell({ metric, isFirst }) {
  const [hovered, setHovered] = useState(false)
  /** Viewport-fixed coords; null until measured so the portal never flashes at (0,0). */
  const [popoverPos, setPopoverPos] = useState(null)
  const timeoutRef = useRef(null)
  const anchorRef = useRef(null)

  useLayoutEffect(() => {
    if (!hovered) {
      setPopoverPos(null)
      return
    }

    const update = () => {
      const el = anchorRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      setPopoverPos({
        top: r.bottom + GAP_PX,
        left: r.left + r.width / 2,
      })
    }

    update()

    const scrollParents = getScrollableAncestors(anchorRef.current)
    scrollParents.forEach((node) => {
      node.addEventListener('scroll', update, true)
    })
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)

    return () => {
      scrollParents.forEach((node) => {
        node.removeEventListener('scroll', update, true)
      })
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [hovered])

  const clearCloseTimer = () => {
    clearTimeout(timeoutRef.current)
  }
  const scheduleClose = () => {
    clearCloseTimer()
    timeoutRef.current = setTimeout(() => setHovered(false), 120)
  }

  const handleEnter = () => {
    clearCloseTimer()
    setHovered(true)
  }
  const handleLeave = () => {
    scheduleClose()
  }

  const trend = (metric.direction || 'flat').toLowerCase()
  const { Icon, valueClass, iconClass } = ribbonStyles(metric.kpi_id, trend, metric.label)
  const changePct = formatChangePct(metric.change_pct)

  const hasPopoverBody = metric && (metric.prior_value != null || metric.cagr != null)
  const showPopover = Boolean(hovered && popoverPos && hasPopoverBody)

  return (
    <div
      ref={anchorRef}
      className="relative flex items-center gap-3 min-w-0 shrink-0 cursor-default"
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
    >
      {!isFirst && <div className="w-px h-8 bg-slate-200 shrink-0" />}
      <div className="min-w-0">
        <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider truncate">
          {metric.label}
        </p>
        <div className="flex items-center gap-1.5 mt-0.5">
          <Icon className={`w-3.5 h-3.5 shrink-0 ${iconClass}`} />
          <span className={`text-sm font-bold tabular-nums ${valueClass}`}>
            {metric.value}
          </span>
        </div>
        {changePct && (
          <p className="text-[9px] text-slate-400 mt-0.5 tabular-nums">
            {changePct} vs prior
          </p>
        )}
      </div>
      {showPopover && typeof document !== 'undefined' && createPortal(
        <MetricPopover
          metric={metric}
          fixedPosition={popoverPos}
          onPopoverEnter={clearCloseTimer}
          onPopoverLeave={scheduleClose}
        />,
        document.body
      )}
    </div>
  )
}

export default function MetricsRibbon({ metrics = [], kpiDataCache }) {
  if (!metrics.length) return null

  return (
    <div className="sticky top-0 z-20 bg-white/95 backdrop-blur-sm border-b border-slate-200 shadow-sm">
      <div className="max-w-5xl mx-auto px-6 py-3">
        <div className="flex items-center justify-between gap-4 overflow-x-auto pb-1">
          {metrics.map((m, i) => (
            <MetricCell key={i} metric={m} isFirst={i === 0} />
          ))}
        </div>
      </div>
    </div>
  )
}
