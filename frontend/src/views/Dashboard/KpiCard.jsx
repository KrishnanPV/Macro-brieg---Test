import { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import {
  LineChart, Line, BarChart, Bar, Area, AreaChart,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceArea,
} from 'recharts'
import {
  Lightbulb, ChevronRight, ChevronDown, RefreshCw,
  Copy, Download, FileSpreadsheet, ZoomOut,
} from 'lucide-react'
import ClipboardCopyButton from '../../components/ui/ClipboardCopyButton'
import ChartFrequencyToggle from '../../components/ui/ChartFrequencyToggle'
import InsightSections from '../../components/ui/InsightSections'
import InsightTabs from '../../components/ui/InsightTabs'
import { SERIES_COLORS, CARD_ACCENT } from '../../lib/colors'
import { formatAbbrevNumber, formatAxisTick } from '../../lib/formatNumbers'

function _forecastSuffix(year, lastActualYear) {
  return lastActualYear != null && year > lastActualYear ? 'F' : ''
}

function isoToQuarterLabel(d, lastActualYear) {
  const dt = new Date(d)
  const q = Math.floor(dt.getMonth() / 3) + 1
  const year = dt.getFullYear()
  return `Q${q} ${year}${_forecastSuffix(year, lastActualYear)}`
}

function isoToYearLabel(d, lastActualYear) {
  const year = new Date(d).getFullYear()
  return `${year}${_forecastSuffix(year, lastActualYear)}`
}

function quarterlyAxisLabel(d, lastActualYear) {
  const dt = new Date(d)
  const q = Math.floor(dt.getMonth() / 3) + 1
  if (q !== 1) return ''
  const year = dt.getFullYear()
  return `${year}${_forecastSuffix(year, lastActualYear)}`
}

function computeAnnualTicks(rows, maxTicks = 15) {
  if (rows.length <= maxTicks) return rows.map(r => r.date)
  const step = Math.ceil(rows.length / maxTicks)
  return rows.filter((_, i) => i % step === 0).map(r => r.date)
}

function escapeCsvCell(v) {
  const s = String(v)
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

function buildKpiTsv(rows, seriesKeys, dateLabelFn) {
  const headers = ['Date', ...seriesKeys.map(sk => sk.key)]
  const lines = [headers.join('\t')]
  for (const row of rows) {
    const cells = [dateLabelFn(row.date), ...seriesKeys.map(sk => {
      const v = row[sk.key]
      return v != null ? String(v) : ''
    })]
    lines.push(cells.join('\t'))
  }
  return lines.join('\n')
}

function buildKpiCsv(rows, seriesKeys, dateLabelFn) {
  const headers = ['Date', ...seriesKeys.map(sk => sk.key)]
  const lines = [headers.map(escapeCsvCell).join(',')]
  for (const row of rows) {
    const cells = [dateLabelFn(row.date), ...seriesKeys.map(sk => row[sk.key] ?? '')]
    lines.push(cells.map(escapeCsvCell).join(','))
  }
  return `\uFEFF${lines.join('\r\n')}`
}

function slugifyFilenamePart(s) {
  return String(s).replace(/[^\w\d]+/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '').slice(0, 60) || 'kpi'
}

function downloadBlob(filename, text, mime) {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function VizModeToggle({ vizMode, onChange }) {
  const options = [
    { key: 'area', label: 'Area' },
    { key: 'line', label: 'Line' },
    { key: 'bar', label: 'Bar' },
    { key: 'table', label: 'Table' },
  ]
  return (
    <div className="inline-flex rounded-lg border border-slate-200 overflow-hidden">
      {options.map(({ key, label }) => (
        <button key={key} type="button" onClick={() => onChange(key)}
          className={`px-2.5 py-1 text-[12px] font-medium transition-all
            ${vizMode === key ? 'bg-mck-navy text-white' : 'bg-white text-slate-500 hover:bg-slate-50'}
            ${key !== 'area' ? 'border-l border-slate-200' : ''}`}
        >{label}</button>
      ))}
    </div>
  )
}

function KpiExportToolbar({ rows, seriesKeys, dateLabelFn, fileBase }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(buildKpiTsv(rows, seriesKeys, dateLabelFn))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* noop */ }
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <button type="button" onClick={handleCopy}
        className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-50 transition">
        <Copy className="w-3.5 h-3.5 text-slate-400" />{copied ? 'Copied' : 'Copy'}
      </button>
      <button type="button" onClick={() => downloadBlob(`${fileBase}.csv`, buildKpiCsv(rows, seriesKeys, dateLabelFn), 'text/csv;charset=utf-8;')}
        className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-50 transition">
        <Download className="w-3.5 h-3.5 text-slate-400" />CSV
      </button>
      <button type="button" onClick={() => downloadBlob(`${fileBase}.xls`, buildKpiTsv(rows, seriesKeys, dateLabelFn), 'application/vnd.ms-excel;charset=utf-8;')}
        className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-50 transition">
        <FileSpreadsheet className="w-3.5 h-3.5 text-slate-400" />Excel
      </button>
    </div>
  )
}

function CustomTooltip({ active, payload, label, formatter }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white rounded-xl shadow-lg border border-slate-200 px-4 py-3 text-xs">
      <p className="font-semibold text-slate-800 mb-1.5">{formatter ? formatter(label) : label}</p>
      {payload.map((entry, i) => (
        <div key={i} className="flex items-center gap-2 py-0.5">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: entry.color }} />
          <span className="text-slate-500 truncate max-w-[180px]">{entry.name}</span>
          <span className="ml-auto font-mono font-medium text-slate-800">{formatAbbrevNumber(entry.value)}</span>
        </div>
      ))}
    </div>
  )
}

function ClickableLegend({ seriesKeys, hiddenSeries, onToggle }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 pt-2 pb-1 text-[11px]">
      {seriesKeys.map(sk => {
        const hidden = hiddenSeries.has(sk.key)
        return (
          <button
            key={sk.key}
            type="button"
            onClick={() => onToggle(sk.key)}
            className={`flex items-center gap-1.5 px-1 py-0.5 rounded transition-all ${hidden ? 'opacity-40' : 'opacity-100 hover:opacity-80'}`}
          >
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: sk.color }} />
            <span className={`text-slate-600 ${hidden ? 'line-through' : ''}`}>{sk.key}</span>
          </button>
        )
      })}
    </div>
  )
}

function normalizedInsightEntry(raw) {
  if (raw == null) return { text: '', newsCatalog: [] }
  if (typeof raw === 'string') return { text: raw, newsCatalog: [] }
  return { text: raw.text || '', newsCatalog: raw.newsCatalog || [] }
}

/** JSON insight response: { text, newsCatalog }. */
async function fetchInsight(url, body, onError) {
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}))
      throw new Error(detail.detail || `HTTP ${resp.status}`)
    }
    const payload = await resp.json()
    return {
      text: payload?.text || '',
      newsCatalog: payload?.newsCatalog || [],
    }
  } catch (e) {
    onError(e.message)
    return { text: '', newsCatalog: [] }
  }
}

export default function KpiCard({
  result, countries, autoTriggerInsight = 0, insightCache = {}, onInsightCached, compact = false,
  onChartFrequencyChange, chartFrequencyLoading = false,
}) {
  const { kpi_id, kpi_name, series, errors, frequency, last_actual_year } = result
  const [vizMode, setVizMode] = useState('area')

  const isMultiCountry = countries.length > 1
  const cachePrefix = `${kpi_id}`

  // --- Interactive legend state ---
  const [hiddenSeries, setHiddenSeries] = useState(new Set())
  const toggleSeries = useCallback((key) => {
    setHiddenSeries(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  // --- Drag-to-zoom state ---
  const [refAreaLeft, setRefAreaLeft] = useState(null)
  const [refAreaRight, setRefAreaRight] = useState(null)
  const [zoomDomain, setZoomDomain] = useState(null)
  const isDragging = useRef(false)

  const handleMouseDown = useCallback((e) => {
    if (e?.activeLabel) {
      isDragging.current = true
      setRefAreaLeft(e.activeLabel)
      setRefAreaRight(null)
    }
  }, [])

  const handleMouseMove = useCallback((e) => {
    if (isDragging.current && e?.activeLabel) {
      setRefAreaRight(e.activeLabel)
    }
  }, [])

  const handleMouseUp = useCallback((e) => {
    if (!isDragging.current) return
    isDragging.current = false

    if (refAreaLeft && refAreaRight && refAreaLeft !== refAreaRight) {
      const [left, right] = [refAreaLeft, refAreaRight].sort()
      setZoomDomain({ left, right })
    }
    setRefAreaLeft(null)
    setRefAreaRight(null)
  }, [refAreaLeft, refAreaRight])

  const resetZoom = useCallback(() => {
    setZoomDomain(null)
    setRefAreaLeft(null)
    setRefAreaRight(null)
  }, [])

  // --- Single-country insight state, seeded from cache ---
  const cachedSingle = normalizedInsightEntry(insightCache[cachePrefix])
  const [insight, setInsight] = useState(cachedSingle.text)
  const [insightNewsCatalog, setInsightNewsCatalog] = useState(cachedSingle.newsCatalog)
  const [insightLoading, setInsightLoading] = useState(false)
  const [insightError, setInsightError] = useState('')
  const [insightOpen, setInsightOpen] = useState(!!cachedSingle.text)

  // --- Multi-country tabbed insight state, seeded from cache ---
  const initialTabbed = {}
  const initialTabbedNews = {}
  for (const key of Object.keys(insightCache)) {
    if (key.startsWith(`${cachePrefix}:`)) {
      const tabKey = key.slice(cachePrefix.length + 1)
      const ent = normalizedInsightEntry(insightCache[key])
      initialTabbed[tabKey] = ent.text
      initialTabbedNews[tabKey] = ent.newsCatalog
    }
  }
  const hasCachedTabs = Object.keys(initialTabbed).length > 0
  const [activeInsightTab, setActiveInsightTab] = useState(hasCachedTabs ? Object.keys(initialTabbed)[0] : null)
  const [tabbedInsights, setTabbedInsights] = useState(initialTabbed)
  const [tabbedNewsCatalog, setTabbedNewsCatalog] = useState(initialTabbedNews)
  const [tabbedLoading, setTabbedLoading] = useState({})
  const [tabbedErrors, setTabbedErrors] = useState({})
  const [insightTabsOpen, setInsightTabsOpen] = useState(hasCachedTabs)
  const tabbedInitiated = useRef(hasCachedTabs)

  const writeCache = (key, payload) => {
    if (!onInsightCached) return
    if (payload && typeof payload === 'object') {
      onInsightCached(key, payload)
    }
  }

  const handleGenerateInsight = async () => {
    if (isMultiCountry) {
      setInsightTabsOpen(true)
      if (!tabbedInitiated.current) {
        tabbedInitiated.current = true
        const firstTab = countries[0]
        setActiveInsightTab(firstTab)
        generateTabInsight(firstTab)
      }
      return
    }
    setInsight(''); setInsightNewsCatalog([]); setInsightError(''); setInsightLoading(true); setInsightOpen(true)
    const final = await fetchInsight('/api/dashboard/insights/country', {
      country: countries[0],
      kpi_result: result,
    }, (msg) => setInsightError(msg))
    setInsight(final.text)
    setInsightNewsCatalog(final.newsCatalog)
    setInsightLoading(false)
    writeCache(cachePrefix, final)
  }

  const generateTabInsight = async (tabKey) => {
    if (tabbedInsights[tabKey] || tabbedLoading[tabKey]) return

    setTabbedLoading(prev => ({ ...prev, [tabKey]: true }))
    setTabbedErrors(prev => ({ ...prev, [tabKey]: '' }))

    const isCrossCountry = tabKey === '__cross__'
    const url = isCrossCountry
      ? '/api/dashboard/insights/cross-country'
      : '/api/dashboard/insights/country'
    const body = isCrossCountry
      ? { countries, kpi_result: result }
      : { country: tabKey, kpi_result: result }

    const final = await fetchInsight(
      url,
      body,
      (msg) => setTabbedErrors(prev => ({ ...prev, [tabKey]: msg })),
    )
    setTabbedInsights(prev => ({ ...prev, [tabKey]: final.text }))
    setTabbedNewsCatalog(prev => ({ ...prev, [tabKey]: final.newsCatalog }))
    setTabbedLoading(prev => ({ ...prev, [tabKey]: false }))
    writeCache(`${cachePrefix}:${tabKey}`, final)
  }

  const handleTabChange = (tabKey) => {
    setActiveInsightTab(tabKey)
    generateTabInsight(tabKey)
  }

  const regenerateTab = (tabKey) => {
    setTabbedInsights(prev => { const n = { ...prev }; delete n[tabKey]; return n })
    setTabbedNewsCatalog(prev => { const n = { ...prev }; delete n[tabKey]; return n })
    setTabbedErrors(prev => ({ ...prev, [tabKey]: '' }))
    setTabbedLoading(prev => ({ ...prev, [tabKey]: false }))
    writeCache(`${cachePrefix}:${tabKey}`, { text: '', newsCatalog: [] })
    setTimeout(() => generateTabInsight(tabKey), 0)
  }

  const autoTriggerRef = useRef(0)
  useEffect(() => {
    if (autoTriggerInsight > 0 && autoTriggerInsight !== autoTriggerRef.current) {
      autoTriggerRef.current = autoTriggerInsight
      if (series.length > 0) {
        handleGenerateInsight()
      }
    }
  }, [autoTriggerInsight])

  if (series.length === 0 && errors.length > 0) {
    const copyText = `KPI ${kpi_id}: ${kpi_name}\n\nThis KPI could not be loaded.\n\n${errors.map(e => `• ${e}`).join('\n')}`
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50/50 shadow-sm overflow-hidden">
        <div className="flex items-start justify-between px-5 py-4 border-b border-red-100/80">
          <h3 className="font-semibold text-slate-800 text-sm">KPI {kpi_id}: {kpi_name}</h3>
          <ClipboardCopyButton text={copyText} title="Copy error details" className="border-red-200 bg-white/90 text-red-900">Copy details</ClipboardCopyButton>
        </div>
        <div className="px-5 py-4">
          <p className="text-[11px] font-medium text-red-900/90 mb-2">This KPI could not be loaded.</p>
          <ul className="list-disc pl-5 space-y-1.5">
            {errors.map((e, i) => <li key={i} className="text-xs text-red-800 leading-snug">{e}</li>)}
          </ul>
        </div>
      </div>
    )
  }

  const { seriesKeys, allRows } = useMemo(() => {
    const dateMap = new Map()
    const keys = []
    series.forEach((s, idx) => {
      const key = `${s.country} — ${s.indicator}`
      keys.push({ key, color: SERIES_COLORS[idx % SERIES_COLORS.length] })
      s.points.forEach(p => {
        if (!dateMap.has(p.date)) dateMap.set(p.date, { date: p.date })
        dateMap.get(p.date)[key] = p.value
      })
    })
    return { seriesKeys: keys, allRows: Array.from(dateMap.values()).sort((a, b) => a.date.localeCompare(b.date)) }
  }, [series])

  const rows = useMemo(() => {
    if (!zoomDomain) return allRows
    return allRows.filter(r => r.date >= zoomDomain.left && r.date <= zoomDomain.right)
  }, [allRows, zoomDomain])

  const isQuarterly = frequency === 'Q'
  const lay = last_actual_year ?? new Date().getFullYear() - 1
  const tooltipFmt = isQuarterly ? (d) => isoToQuarterLabel(d, lay) : (d) => isoToYearLabel(d, lay)
  const axisFmt = isQuarterly ? (d) => quarterlyAxisLabel(d, lay) : (d) => isoToYearLabel(d, lay)
  const ticks = isQuarterly ? rows.map(r => r.date) : computeAnnualTicks(rows)
  const exportFileBase = `kpi_${kpi_id}_${slugifyFilenamePart(kpi_name)}`
  const chartHeight = compact ? 220 : 320

  const visibleSeriesKeys = seriesKeys.filter(sk => !hiddenSeries.has(sk.key))

  const chartEvents = {
    onMouseDown: handleMouseDown,
    onMouseMove: handleMouseMove,
    onMouseUp: handleMouseUp,
  }

  const zoomRefArea = refAreaLeft && refAreaRight ? (
    <ReferenceArea x1={refAreaLeft} x2={refAreaRight} strokeOpacity={0.3} fill="#24477F" fillOpacity={0.15} />
  ) : null

  return (
    <div
      className="rounded-2xl border border-slate-200/80 bg-white shadow-sm hover:shadow-md transition-shadow duration-200 overflow-hidden"
      style={{ borderLeftWidth: 3, borderLeftColor: CARD_ACCENT }}
    >
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-100/80">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">KPI {kpi_id}</span>
          </div>
          <h3 className="font-semibold text-mck-navy text-[15px] leading-tight">{kpi_name}</h3>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 mt-3 pt-3 border-t border-slate-100/80">
          <div className="flex flex-wrap items-center gap-2">
            {onChartFrequencyChange && (
              <ChartFrequencyToggle
                value={frequency}
                loading={chartFrequencyLoading}
                onChange={(f) => onChartFrequencyChange(kpi_id, f)}
              />
            )}
            <VizModeToggle vizMode={vizMode} onChange={setVizMode} />
            {zoomDomain && (
              <button type="button" onClick={resetZoom}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg border border-slate-200 bg-white text-[11px] font-medium text-mck-deep hover:bg-slate-50 transition">
                <ZoomOut className="w-3.5 h-3.5" />Reset Zoom
              </button>
            )}
          </div>
          {rows.length > 0 && !compact && (
            <KpiExportToolbar rows={rows} seriesKeys={seriesKeys} dateLabelFn={tooltipFmt} fileBase={exportFileBase} />
          )}
        </div>
      </div>

      {/* Chart / Table */}
      <div className="px-5 py-4">
        {errors.length > 0 && (
          <div className="mb-3">
            {errors.map((e, i) => <p key={i} className="text-[11px] text-amber-600">⚠ {e}</p>)}
          </div>
        )}
        {allRows.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-center">
            <p className="text-xs text-slate-500">No data points returned for this KPI in the selected time range.</p>
          </div>
        ) : vizMode === 'table' ? (
          <div className="overflow-x-auto max-h-80 overflow-y-auto rounded-xl border border-slate-100">
            <table className="min-w-full text-xs border-collapse">
              <thead>
                <tr className="bg-slate-50">
                  <th className="sticky top-0 bg-slate-50 border-b border-slate-200 px-3 py-2.5 text-left font-semibold text-slate-600">Date</th>
                  {seriesKeys.map(sk => <th key={sk.key} className="sticky top-0 bg-slate-50 border-b border-slate-200 px-3 py-2.5 text-right font-semibold text-slate-600">{sk.key}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map(row => (
                  <tr key={row.date} className="hover:bg-mck-blue/5 transition">
                    <td className="border-b border-slate-100 px-3 py-2 text-slate-700 font-medium">{tooltipFmt(row.date)}</td>
                    {seriesKeys.map(sk => <td key={sk.key} className="border-b border-slate-100 px-3 py-2 text-right font-mono text-slate-700">{formatAbbrevNumber(row[sk.key])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : vizMode === 'bar' ? (
          <>
            <ResponsiveContainer width="100%" height={chartHeight}>
              <BarChart data={rows} {...chartEvents}
                margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tickFormatter={axisFmt} ticks={ticks} interval={0} tick={{ fontSize: 10, fill: '#94a3b8', fontFamily: 'inherit' }} height={30} axisLine={{ stroke: '#e2e8f0' }} padding={{ left: 4, right: 4 }} allowDataOverflow={!!zoomDomain} />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8', fontFamily: 'inherit' }} tickFormatter={formatAxisTick} axisLine={false} tickLine={false} allowDataOverflow={!!zoomDomain} />
                <Tooltip content={<CustomTooltip formatter={tooltipFmt} />} />
                {visibleSeriesKeys.map(sk => <Bar key={sk.key} dataKey={sk.key} fill={sk.color} radius={[4, 4, 0, 0]} />)}
                {zoomRefArea}
              </BarChart>
            </ResponsiveContainer>
            <ClickableLegend seriesKeys={seriesKeys} hiddenSeries={hiddenSeries} onToggle={toggleSeries} />
          </>
        ) : vizMode === 'area' ? (
          <>
            <ResponsiveContainer width="100%" height={chartHeight}>
              <AreaChart data={rows} {...chartEvents}
                margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
                <defs>
                  {visibleSeriesKeys.map(sk => (
                    <linearGradient key={sk.key} id={`grad-${kpi_id}-${sk.key.replace(/\W/g, '_')}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={sk.color} stopOpacity={0.15} />
                      <stop offset="95%" stopColor={sk.color} stopOpacity={0} />
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tickFormatter={axisFmt} ticks={ticks} interval={0} tick={{ fontSize: 10, fill: '#94a3b8', fontFamily: 'inherit' }} height={30} axisLine={{ stroke: '#e2e8f0' }} padding={{ left: 4, right: 4 }} allowDataOverflow={!!zoomDomain} />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8', fontFamily: 'inherit' }} tickFormatter={formatAxisTick} axisLine={false} tickLine={false} allowDataOverflow={!!zoomDomain} />
                <Tooltip content={<CustomTooltip formatter={tooltipFmt} />} />
                {visibleSeriesKeys.map(sk => (
                  <Area key={sk.key} type="linear" dataKey={sk.key} stroke={sk.color}
                    fill={`url(#grad-${kpi_id}-${sk.key.replace(/\W/g, '_')})`}
                    strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, fill: '#fff' }} />
                ))}
                {zoomRefArea}
              </AreaChart>
            </ResponsiveContainer>
            <ClickableLegend seriesKeys={seriesKeys} hiddenSeries={hiddenSeries} onToggle={toggleSeries} />
          </>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={chartHeight}>
              <LineChart data={rows} {...chartEvents}
                margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tickFormatter={axisFmt} ticks={ticks} interval={0} tick={{ fontSize: 10, fill: '#94a3b8', fontFamily: 'inherit' }} height={30} axisLine={{ stroke: '#e2e8f0' }} padding={{ left: 4, right: 4 }} allowDataOverflow={!!zoomDomain} />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8', fontFamily: 'inherit' }} tickFormatter={formatAxisTick} axisLine={false} tickLine={false} allowDataOverflow={!!zoomDomain} />
                <Tooltip content={<CustomTooltip formatter={tooltipFmt} />} />
                {visibleSeriesKeys.map(sk => <Line key={sk.key} type="linear" dataKey={sk.key} stroke={sk.color} dot={false} strokeWidth={2} activeDot={{ r: 4, strokeWidth: 2, fill: '#fff' }} />)}
                {zoomRefArea}
              </LineChart>
            </ResponsiveContainer>
            <ClickableLegend seriesKeys={seriesKeys} hiddenSeries={hiddenSeries} onToggle={toggleSeries} />
          </>
        )}
      </div>

      {/* Insights */}
      <div className="px-5 pb-5">
        <div className="border-t border-slate-100/80 pt-4">
          {isMultiCountry ? (
            !insightTabsOpen ? (
              <button onClick={handleGenerateInsight} disabled={series.length === 0}
                className="inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold text-mck-deep bg-mck-blue/5 rounded-xl hover:bg-mck-blue/10 transition disabled:opacity-40 disabled:cursor-not-allowed">
                <Lightbulb className="w-4 h-4" />Generate Insights
              </button>
            ) : (
              <div>
                <button type="button" onClick={() => setInsightTabsOpen(o => !o)}
                  className="flex items-center gap-2 text-left mb-3 group">
                  <ChevronDown className={`w-4 h-4 text-mck-deep shrink-0 transition-transform duration-200 ${insightTabsOpen ? '' : '-rotate-90'}`} />
                  <span className="text-sm font-semibold text-mck-navy">Insights</span>
                </button>
                <InsightTabs
                  tabs={[
                    ...countries.map(c => ({
                      key: c,
                      label: c,
                      loading: !!tabbedLoading[c],
                    })),
                    { key: '__cross__', label: 'Cross-Country', loading: !!tabbedLoading['__cross__'] },
                  ]}
                  activeTab={activeInsightTab || countries[0]}
                  onTabChange={handleTabChange}
                >
                  {(() => {
                    const tab = activeInsightTab || countries[0]
                    const text = tabbedInsights[tab]
                    const tabLoading = tabbedLoading[tab]
                    const tabError = tabbedErrors[tab]
                    return (
                      <div>
                        <div className="flex items-center justify-end gap-1 mb-2">
                          {text && !tabLoading && <ClipboardCopyButton text={text} className="border-mck-pale bg-white/90 text-mck-navy">Copy</ClipboardCopyButton>}
                          <button type="button" onClick={() => regenerateTab(tab)} className="rounded-lg border border-mck-pale bg-white/90 px-2 py-1 text-[11px] font-medium text-mck-deep hover:bg-white transition" title="Regenerate">
                            <RefreshCw className="w-3 h-3" />
                          </button>
                        </div>
                        {tabError && <p className="text-xs text-red-600 mb-2">{tabError}</p>}
                        {text && (
                          <InsightSections
                            text={text}
                            newsCatalog={tabbedNewsCatalog[tab] || []}
                          />
                        )}
                        {!text && tabLoading && <InsightSkeleton />}
                        {!text && !tabLoading && !tabError && <p className="text-xs text-slate-400 italic">Click this tab to generate insights for {tab === '__cross__' ? 'cross-country analysis' : tab}.</p>}
                      </div>
                    )
                  })()}
                </InsightTabs>
              </div>
            )
          ) : (
            (() => {
              const hasInsight = insight || insightLoading || insightError
              return !hasInsight ? (
                <button onClick={handleGenerateInsight} disabled={series.length === 0}
                  className="inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold text-mck-deep bg-mck-blue/5 rounded-xl hover:bg-mck-blue/10 transition disabled:opacity-40 disabled:cursor-not-allowed">
                  <Lightbulb className="w-4 h-4" />Generate Insights
                </button>
              ) : (
                <div className="rounded-xl border border-mck-pale/40 bg-gradient-to-br from-mck-blue/3 to-slate-50/50 overflow-hidden">
                  <div className="flex items-center gap-2 px-4 py-3 hover:bg-mck-blue/5 transition">
                    <button type="button" onClick={() => setInsightOpen(o => !o)} className="flex-1 flex items-center gap-2 text-left min-w-0">
                      <ChevronRight className={`w-4 h-4 text-mck-deep shrink-0 transition-transform duration-200 ${insightOpen ? 'rotate-90' : ''}`} />
                      <span className="text-sm font-semibold text-mck-navy">Insights</span>
                      {insightLoading && <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-mck-sky border-t-transparent animate-spin shrink-0" />}
                    </button>
                    <div className="flex items-center gap-1 shrink-0">
                      {insight && !insightLoading && <ClipboardCopyButton text={insight} className="border-mck-pale bg-white/90 text-mck-navy">Copy</ClipboardCopyButton>}
                      <button type="button" onClick={handleGenerateInsight} className="rounded-lg border border-mck-pale bg-white/90 px-2 py-1 text-[11px] font-medium text-mck-deep hover:bg-white transition" title="Regenerate">
                        <RefreshCw className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                  {insightOpen && (
                    <div className="px-5 pb-4 pt-1">
                      {insightError && <p className="text-xs text-red-600 mb-2">{insightError}</p>}
                      {insight && (
                        <InsightSections text={insight} newsCatalog={insightNewsCatalog} />
                      )}
                      {!insight && insightLoading && <InsightSkeleton />}
                    </div>
                  )}
                </div>
              )
            })()
          )}
        </div>
      </div>
    </div>
  )
}

function InsightSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="h-16 bg-slate-100 rounded-lg" />
      <div className="space-y-2">
        <div className="h-3 bg-slate-100 rounded w-3/4" />
        <div className="h-3 bg-slate-100 rounded w-full" />
        <div className="h-3 bg-slate-100 rounded w-5/6" />
      </div>
      <div className="space-y-2">
        <div className="h-3 bg-slate-100 rounded w-2/3" />
        <div className="h-3 bg-slate-100 rounded w-4/5" />
      </div>
    </div>
  )
}
