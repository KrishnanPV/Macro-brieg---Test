import { useState, useMemo, useRef, useEffect } from 'react'
import {
  ComposedChart, Area, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceArea,
} from 'recharts'
import { Copy, FileSpreadsheet, TrendingUp, X } from 'lucide-react'
import ChartFrequencyToggle from '../../../components/ui/ChartFrequencyToggle'
import { SERIES_COLORS } from '../../../lib/colors'
import { formatAbbrevNumber, formatAxisTick } from '../../../lib/formatNumbers'
import FdiBenchmarkChart from './FdiBenchmarkChart'

const SCALE_WORDS = {
  billions: 1e9, billion: 1e9,
  millions: 1e6, million: 1e6,
  thousands: 1e3, thousand: 1e3,
}

function getScaleMultiplier(unit) {
  if (!unit) return 1
  for (const token of unit.toLowerCase().split(/\s+/)) {
    if (SCALE_WORDS[token]) return SCALE_WORDS[token]
  }
  return 1
}

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

function CustomTooltip({ active, payload, label, dateFormatter }) {
  if (!active || !payload?.length) return null
  const fmt = dateFormatter || isoToYearLabel
  return (
    <div className="bg-white rounded-lg shadow-lg border border-slate-200 px-3 py-2 text-xs">
      <p className="font-semibold text-slate-800 mb-1">{fmt(label)}</p>
      {payload.map((entry, i) => (
        <div key={i} className="flex items-center gap-2 py-0.5">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: entry.color }} />
          <span className="text-slate-500 truncate max-w-[160px]">{entry.name}</span>
          <span className="ml-auto font-mono font-medium text-slate-800">
            {formatAbbrevNumber(entry.value)}
          </span>
        </div>
      ))}
    </div>
  )
}

const KPI_CHART_DEFAULTS = {
  '3':  { vizMode: 'line', freq: 'Q' },
  '2':  { vizMode: 'bar',  freq: 'A' },
  '11': { vizMode: 'bar',  freq: 'A' },
  '5':  { vizMode: 'line', freq: 'Q' },
}
const DEFAULT_CHART = { vizMode: 'line', freq: 'Q' }

function buildRowsFromSeries(seriesList, topUnit) {
  const dateMap = new Map()
  const keys = []
  seriesList.forEach((s, idx) => {
    const key = s.indicator
    const mult = getScaleMultiplier(s.unit || topUnit || '')
    keys.push({ key, color: SERIES_COLORS[idx % SERIES_COLORS.length] })
    s.points.forEach(p => {
      if (p.value == null) return
      if (!dateMap.has(p.date)) dateMap.set(p.date, { date: p.date })
      dateMap.get(p.date)[key] = p.value * mult
    })
  })
  return {
    seriesKeys: keys,
    rows: Array.from(dateMap.values()).sort((a, b) => a.date.localeCompare(b.date)),
  }
}

function buildTsv(rows, seriesKeys, dateLabelFn) {
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

function downloadBlob(filename, text, mime) {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function slugify(s) {
  return String(s).replace(/[^\w\d]+/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '').slice(0, 60) || 'kpi'
}

const OIL_OVERLAY_KEY = '__oil_price__'
const OIL_OVERLAY_COLOR = '#d97706'

function computeCagr(startVal, endVal, years) {
  if (startVal == null || endVal == null || years <= 0 || startVal === 0) return null
  if (startVal < 0 || endVal < 0) {
    // CAGR formula doesn't apply when signs differ or values are negative;
    // fall back to simple annualized change: (end - start) / |start| / years
    return ((endVal - startVal) / Math.abs(startVal) / years) * 100
  }
  return ((endVal / startVal) ** (1 / years) - 1) * 100
}

function extractYearsFromRows(rows) {
  const years = new Set()
  for (const r of rows) {
    const y = new Date(r.date).getFullYear()
    if (!isNaN(y)) years.add(y)
  }
  return [...years].sort((a, b) => a - b)
}

function findRowValueForYear(rows, year, seriesKey) {
  const candidates = rows.filter(r => new Date(r.date).getFullYear() === year && r[seriesKey] != null)
  if (!candidates.length) return null
  return candidates[candidates.length - 1][seriesKey]
}

function shortenIndicator(name) {
  const parts = name.split(',').map(s => s.trim())
  if (parts.length <= 2) return name.length > 30 ? name.slice(0, 28) + '...' : name
  return parts.slice(0, 2).join(', ')
}

function CagrPopup({ seriesKeys, rows, onCalculate, onClose }) {
  const popupRef = useRef(null)
  const years = useMemo(() => extractYearsFromRows(rows), [rows])
  const [selectedSeries, setSelectedSeries] = useState(seriesKeys[0]?.key || '')
  const [startYear, setStartYear] = useState(years.length >= 2 ? years[0] : '')
  const [endYear, setEndYear] = useState(years.length >= 2 ? years[years.length - 1] : '')

  useEffect(() => {
    function handleClickOutside(e) {
      if (popupRef.current && !popupRef.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [onClose])

  const validEndYears = years.filter(y => y > Number(startYear))
  const canCalculate = selectedSeries && startYear && endYear && Number(endYear) > Number(startYear)

  const handleSubmit = () => {
    if (!canCalculate) return
    const sy = Number(startYear)
    const ey = Number(endYear)
    const startVal = findRowValueForYear(rows, sy, selectedSeries)
    const endVal = findRowValueForYear(rows, ey, selectedSeries)
    const yrs = ey - sy
    const cagr = computeCagr(startVal, endVal, yrs)
    if (cagr == null) return
    onCalculate({
      seriesKey: selectedSeries,
      startYear: sy,
      endYear: ey,
      years: yrs,
      cagr,
    })
  }

  return (
    <div ref={popupRef} className="absolute right-0 top-full mt-1 z-50 bg-white rounded-xl border border-slate-200 shadow-xl p-3 w-64">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-semibold text-slate-600">CAGR Calculator</span>
        <button type="button" onClick={onClose} className="p-0.5 rounded hover:bg-slate-100 transition">
          <X className="w-3.5 h-3.5 text-slate-400" />
        </button>
      </div>
      {seriesKeys.length > 1 && (
        <div className="mb-2">
          <label className="text-[10px] text-slate-400 mb-0.5 block">Indicator</label>
          <select value={selectedSeries} onChange={e => setSelectedSeries(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[11px] text-slate-700 outline-none focus:border-blue-400">
            {seriesKeys.map(sk => (
              <option key={sk.key} value={sk.key}>{sk.key}</option>
            ))}
          </select>
        </div>
      )}
      <div className="flex gap-2 mb-2">
        <div className="flex-1">
          <label className="text-[10px] text-slate-400 mb-0.5 block">Start Year</label>
          <select value={startYear} onChange={e => {
            setStartYear(e.target.value)
            if (Number(endYear) <= Number(e.target.value)) {
              const next = years.find(y => y > Number(e.target.value))
              if (next) setEndYear(next)
            }
          }}
            className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[11px] text-slate-700 outline-none focus:border-blue-400 tabular-nums">
            {years.slice(0, -1).map(y => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="text-[10px] text-slate-400 mb-0.5 block">End Year</label>
          <select value={endYear} onChange={e => setEndYear(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[11px] text-slate-700 outline-none focus:border-blue-400 tabular-nums">
            {validEndYears.map(y => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>
      </div>
      <button type="button" onClick={handleSubmit} disabled={!canCalculate}
        className="w-full px-3 py-1.5 text-[11px] font-semibold text-white rounded-lg transition-all
          bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700
          disabled:opacity-40 disabled:cursor-not-allowed">
        Calculate
      </button>
    </div>
  )
}

function CagrXAxisTick({ x, y, payload, axisFmt, cagrResult }) {
  const label = axisFmt(payload.value)
  if (!label) return null
  const year = new Date(payload.value).getFullYear()
  const isHighlighted = cagrResult && year >= cagrResult.startYear && year <= cagrResult.endYear
  const isEndpoint = cagrResult && (year === cagrResult.startYear || year === cagrResult.endYear)
  return (
    <text x={x} y={y + 10} textAnchor="middle"
      fontSize={isEndpoint ? 11 : 10}
      fontWeight={isEndpoint ? 700 : isHighlighted ? 600 : 400}
      fill={isEndpoint ? '#4f46e5' : isHighlighted ? '#6366f1' : '#94a3b8'}>
      {label}
    </text>
  )
}

export default function InlineChartBlock({
  kpiId,
  kpiDataCache = [],
  compact = false,
  fdiBenchmark = null,
  fdiFlowMode = 'chart',
  onFdiFlowModeChange,
  onFdiBenchmarkYearChange,
}) {
  const isFdiKpi =
    String(kpiId) === '4'
  const hasFdiBenchmark =
    Array.isArray(fdiBenchmark?.countries) &&
    fdiBenchmark.countries.length > 0
  const showFdiBenchmark =
    isFdiKpi &&
    hasFdiBenchmark &&
    fdiFlowMode !== 'chart'

  const kpiResult = kpiDataCache.find(r => String(r.kpi_id) === String(kpiId))
  const defaults = KPI_CHART_DEFAULTS[String(kpiId)] || DEFAULT_CHART
  const hasDualFreq = !!(kpiResult?.series_annual?.length)

  const [vizMode, setVizMode] = useState(defaults.vizMode)
  const [freq, setFreq] = useState(hasDualFreq ? defaults.freq : 'Q')
  const [copied, setCopied] = useState(false)
  const [cagrPopupOpen, setCagrPopupOpen] = useState(false)
  const [cagrResult, setCagrResult] = useState(null)

  const activeSeries = (freq === 'A' && hasDualFreq)
    ? kpiResult.series_annual
    : kpiResult?.series

  const isQuarterly = freq === 'Q' && kpiResult?.frequency === 'Q'

  const isOilGdpKpi = String(kpiId) === '2'
  const oilOverlay = isOilGdpKpi ? kpiResult?.oil_price_overlay : null
  const hasOilOverlay = !!(oilOverlay?.points?.length)

  const { seriesKeys, rows, kpiName, unitLabel } = useMemo(() => {
    if (!kpiResult || !activeSeries?.length) {
      return { seriesKeys: [], rows: [], kpiName: '', unitLabel: '' }
    }
    const { seriesKeys: sk, rows: r } = buildRowsFromSeries(activeSeries, kpiResult.unit)
    const unit = activeSeries[0]?.unit || kpiResult.unit || ''
    return { seriesKeys: sk, rows: r, kpiName: kpiResult.kpi_name, unitLabel: unit }
  }, [kpiResult, activeSeries])

  const isPercentageUnit = unitLabel.trim().startsWith('%')

  const oilByYear = useMemo(() => {
    if (!hasOilOverlay) return null
    const map = new Map()
    for (const p of oilOverlay.points) {
      if (p.value != null) {
        const y = new Date(p.date).getFullYear()
        if (!isNaN(y)) map.set(y, p.value)
      }
    }
    return map.size ? map : null
  }, [oilOverlay, hasOilOverlay])

  const chartRows = useMemo(() => {
    if (!oilByYear) return rows
    return rows.map(r => {
      const row = { ...r }
      const y = new Date(r.date).getFullYear()
      row[OIL_OVERLAY_KEY] = oilByYear.get(y) ?? null
      return row
    })
  }, [rows, oilByYear])

  const cagrHighlight = useMemo(() => {
    if (!cagrResult) return null
    const startRows = rows.filter(r => new Date(r.date).getFullYear() === cagrResult.startYear)
    const endRows = rows.filter(r => new Date(r.date).getFullYear() === cagrResult.endYear)
    if (!startRows.length || !endRows.length) return null
    return { x1: startRows[0].date, x2: endRows[endRows.length - 1].date }
  }, [rows, cagrResult])

  if (showFdiBenchmark) {
    return (
      <FdiBenchmarkChart
        benchmarkData={fdiBenchmark}
        flowMode={fdiFlowMode}
        onFlowModeChange={onFdiFlowModeChange}
        onYearRangeChange={onFdiBenchmarkYearChange}
      />
    )
  }

  if (!rows.length) return null

  const chartHeight = compact ? 180 : 220
  const lay = kpiResult?.last_actual_year ?? new Date().getFullYear() - 1
  const tooltipFmt = isQuarterly ? (d) => isoToQuarterLabel(d, lay) : (d) => isoToYearLabel(d, lay)
  const axisFmt = isQuarterly ? (d) => quarterlyAxisLabel(d, lay) : (d) => isoToYearLabel(d, lay)
  const ticks = isQuarterly ? rows.map(r => r.date) : computeAnnualTicks(rows)
  const fileBase = `kpi_${kpiId}_${slugify(kpiName)}`
  const activeVizMode = vizMode
  const fdiViewMode = hasFdiBenchmark
    ? (['chart', 'inflow', 'outflow'].includes(fdiFlowMode) ? fdiFlowMode : 'chart')
    : 'chart'
  const isBenchmarkMode = isFdiKpi && fdiViewMode !== 'chart'

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(buildTsv(rows, seriesKeys, tooltipFmt))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* noop */ }
  }

  const handleExcel = () => {
    downloadBlob(`${fileBase}.xls`, buildTsv(rows, seriesKeys, tooltipFmt), 'application/vnd.ms-excel;charset=utf-8;')
  }

  const handleCagrCalculate = (result) => {
    setCagrResult(result)
    setCagrPopupOpen(false)
  }

  const cagrColor = cagrResult ? (cagrResult.cagr >= 0 ? '#16a34a' : '#dc2626') : '#16a34a'
  const cagrLabel = cagrResult
    ? `${cagrResult.cagr >= 0 ? '+' : ''}${cagrResult.cagr.toFixed(1)}% (${cagrResult.years}Y)`
    : ''
  const cagrTag = cagrResult && seriesKeys.length > 1
    ? shortenIndicator(cagrResult.seriesKey)
    : ''

  return (
    <div className={compact
      ? "rounded-lg overflow-hidden"
      : "my-4 rounded-xl border border-slate-200/80 bg-white shadow-sm overflow-hidden"
    }>
      <div className={compact
        ? "px-3 py-2 border-b border-slate-100/60"
        : "px-4 py-3 border-b border-slate-100 bg-slate-50/50"
      }>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              {kpiName}
            </p>
            {unitLabel && (
              <p className="text-[10px] text-slate-400 leading-tight mt-0.5">{unitLabel}</p>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            {hasDualFreq && (
              <div className={isFdiKpi && isBenchmarkMode ? 'opacity-0 pointer-events-none' : ''}>
                <ChartFrequencyToggle value={freq} loading={false} onChange={setFreq} />
              </div>
            )}
            <div className={`inline-flex rounded-lg border border-slate-200 overflow-hidden ${
              isFdiKpi && isBenchmarkMode ? 'opacity-0 pointer-events-none' : ''
            }`}>
              <button type="button" onClick={() => setVizMode('bar')}
                className={`px-2 py-1 text-[11px] font-medium transition-all ${
                  vizMode === 'bar' ? 'bg-mck-navy text-white' : 'bg-white text-slate-500 hover:bg-slate-50'
                }`}
              >Bar</button>
              <button type="button" onClick={() => setVizMode('line')}
                className={`px-2 py-1 text-[11px] font-medium transition-all border-l border-slate-200 ${
                  vizMode === 'line' ? 'bg-mck-navy text-white' : 'bg-white text-slate-500 hover:bg-slate-50'
                }`}
              >Line</button>
            </div>
            <div className="relative"
              {...(isPercentageUnit ? { title: 'CAGR is only meaningful for absolute quantities' } : {})}>
              <button type="button"
                disabled={isPercentageUnit}
                onClick={() => setCagrPopupOpen(v => !v)}
                className={`px-2 py-1 text-[11px] font-semibold rounded-lg transition-all ${
                  isPercentageUnit
                    ? 'bg-slate-100 text-slate-400 border border-slate-200 cursor-not-allowed'
                    : cagrPopupOpen
                      ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-600/25'
                      : 'bg-indigo-50 text-indigo-700 border border-indigo-300 hover:bg-indigo-100'
                }`}>
                <TrendingUp className="w-3 h-3 inline-block -mt-0.5 mr-0.5" />CAGR
              </button>
              {cagrPopupOpen && !isPercentageUnit && (
                <CagrPopup
                  seriesKeys={seriesKeys}
                  rows={rows}
                  onCalculate={handleCagrCalculate}
                  onClose={() => setCagrPopupOpen(false)}
                />
              )}
            </div>
            {isFdiKpi && (
              <>
                <div className="w-px h-4 bg-slate-200 mx-0.5" />
                <button
                  type="button"
                  disabled={!hasFdiBenchmark}
                  onClick={() => onFdiFlowModeChange?.(isBenchmarkMode ? 'chart' : 'inflow')}
                  className={`px-2.5 py-1 text-[11px] font-semibold rounded-lg transition-all ${
                    isBenchmarkMode
                      ? 'bg-amber-500 text-white shadow-sm shadow-amber-500/25'
                      : 'bg-amber-50 text-amber-700 border border-amber-300 hover:bg-amber-100'
                  } ${!hasFdiBenchmark ? 'opacity-40 cursor-not-allowed hover:bg-amber-50' : ''}`}
                >
                  Benchmark
                </button>
              </>
            )}
          </div>
        </div>
      </div>
      <div className={compact ? "px-2 py-2" : "px-4 py-3"}>
        <div className="relative">
          {cagrResult && (
            <div className="absolute top-1 left-14 z-10 flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-bold shadow-sm border"
                style={{
                  color: cagrColor,
                  backgroundColor: cagrResult.cagr >= 0 ? '#f0fdf4' : '#fef2f2',
                  borderColor: cagrResult.cagr >= 0 ? '#bbf7d0' : '#fecaca',
                }}>
                {cagrLabel}
                {cagrTag && <span className="font-normal text-[9px] opacity-70 ml-0.5">{cagrTag}</span>}
              </span>
              <button type="button" onClick={() => setCagrResult(null)}
                className="p-0.5 rounded hover:bg-slate-100 transition">
                <X className="w-3 h-3 text-slate-400" />
              </button>
            </div>
          )}
          <ResponsiveContainer width="100%" height={chartHeight}>
            <ComposedChart data={chartRows}>
              {activeVizMode === 'line' && (
                <defs>
                  {seriesKeys.map(sk => (
                    <linearGradient key={sk.key} id={`brief-grad-${kpiId}-${sk.key.replace(/\W/g, '_')}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={sk.color} stopOpacity={0.15} />
                      <stop offset="95%" stopColor={sk.color} stopOpacity={0} />
                    </linearGradient>
                  ))}
                </defs>
              )}
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="date" ticks={ticks} interval={0} height={24} axisLine={{ stroke: '#e2e8f0' }}
                {...(cagrResult
                  ? { tick: <CagrXAxisTick axisFmt={axisFmt} cagrResult={cagrResult} /> }
                  : { tickFormatter: axisFmt, tick: { fontSize: 10, fill: '#94a3b8' } }
                )} />
              <YAxis yAxisId="left" tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={formatAxisTick}
                axisLine={false} tickLine={false} width={52} />
              {hasOilOverlay && (
                <YAxis yAxisId="right" orientation="right"
                  tick={{ fontSize: 9, fill: OIL_OVERLAY_COLOR }} tickFormatter={formatAxisTick}
                  axisLine={false} tickLine={false} width={48}
                  label={{ value: oilOverlay.unit || '', angle: 90, position: 'insideRight',
                    style: { fontSize: 9, fill: OIL_OVERLAY_COLOR }, dx: 12 }} />
              )}
              <Tooltip content={<CustomTooltip dateFormatter={tooltipFmt} />} />
              {activeVizMode === 'bar'
                ? seriesKeys.map(sk => (
                    <Bar key={sk.key} dataKey={sk.key} fill={sk.color} stackId="a" yAxisId="left" />
                  ))
                : seriesKeys.map(sk => (
                    <Area key={sk.key} type="monotone" dataKey={sk.key} stroke={sk.color}
                      fill={`url(#brief-grad-${kpiId}-${sk.key.replace(/\W/g, '_')})`}
                      strokeWidth={2} dot={false} activeDot={{ r: 3, strokeWidth: 2, fill: '#fff' }}
                      yAxisId="left" />
                  ))
              }
              {hasOilOverlay && (
                <Line dataKey={OIL_OVERLAY_KEY} yAxisId="right" stroke={OIL_OVERLAY_COLOR}
                  strokeWidth={2} strokeDasharray="4 2" dot={false} connectNulls
                  name={oilOverlay.indicator || 'Brent (LCU)'} />
              )}
              {cagrHighlight && (
                <ReferenceArea x1={cagrHighlight.x1} x2={cagrHighlight.x2} yAxisId="left"
                  fill={cagrColor} fillOpacity={0.06}
                  stroke={cagrColor} strokeOpacity={0.25} strokeDasharray="4 2" />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        {(seriesKeys.length > 1 || hasOilOverlay) && (
          <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 pt-1 text-[10px]">
            {seriesKeys.map(sk => (
              <div key={sk.key} className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: sk.color }} />
                <span className="text-slate-500">{sk.key}</span>
              </div>
            ))}
            {hasOilOverlay && (
              <div className="flex items-center gap-1.5">
                <span className="w-3 border-t-2 border-dashed" style={{ borderColor: OIL_OVERLAY_COLOR }} />
                <span className="text-slate-500">{oilOverlay.indicator || 'Brent (LCU)'}</span>
              </div>
            )}
          </div>
        )}
        <div className="flex items-center gap-1.5 pt-2">
          <button type="button" onClick={handleCopy}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[10px] font-medium text-slate-500 hover:bg-slate-50 transition">
            <Copy className="w-3 h-3 text-slate-400" />{copied ? 'Copied' : 'Copy'}
          </button>
          <button type="button" onClick={handleExcel}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[10px] font-medium text-slate-500 hover:bg-slate-50 transition">
            <FileSpreadsheet className="w-3 h-3 text-slate-400" />Excel
          </button>
        </div>
      </div>
    </div>
  )
}
