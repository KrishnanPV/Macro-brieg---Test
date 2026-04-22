import { useState, useMemo } from 'react'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { Copy, FileSpreadsheet } from 'lucide-react'
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

  const activeSeries = (freq === 'A' && hasDualFreq)
    ? kpiResult.series_annual
    : kpiResult?.series

  const isQuarterly = freq === 'Q' && kpiResult?.frequency === 'Q'

  const { seriesKeys, rows, kpiName, unitLabel } = useMemo(() => {
    if (!kpiResult || !activeSeries?.length) {
      return { seriesKeys: [], rows: [], kpiName: '', unitLabel: '' }
    }
    const { seriesKeys: sk, rows: r } = buildRowsFromSeries(activeSeries, kpiResult.unit)
    const unit = activeSeries[0]?.unit || kpiResult.unit || ''
    return { seriesKeys: sk, rows: r, kpiName: kpiResult.kpi_name, unitLabel: unit }
  }, [kpiResult, activeSeries])

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
        <ResponsiveContainer width="100%" height={chartHeight}>
          {activeVizMode === 'bar' ? (
            <BarChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="date" tickFormatter={axisFmt} ticks={ticks} interval={0}
                tick={{ fontSize: 10, fill: '#94a3b8' }} height={24} axisLine={{ stroke: '#e2e8f0' }} />
              <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={formatAxisTick}
                axisLine={false} tickLine={false} width={52} />
              <Tooltip content={<CustomTooltip dateFormatter={tooltipFmt} />} />
              {seriesKeys.map(sk => (
                <Bar key={sk.key} dataKey={sk.key} fill={sk.color} stackId="a" />
              ))}
            </BarChart>
          ) : (
            <AreaChart data={rows}>
              <defs>
                {seriesKeys.map(sk => (
                  <linearGradient key={sk.key} id={`brief-grad-${kpiId}-${sk.key.replace(/\W/g, '_')}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={sk.color} stopOpacity={0.15} />
                    <stop offset="95%" stopColor={sk.color} stopOpacity={0} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="date" tickFormatter={axisFmt} ticks={ticks} interval={0}
                tick={{ fontSize: 10, fill: '#94a3b8' }} height={24} axisLine={{ stroke: '#e2e8f0' }} />
              <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={formatAxisTick}
                axisLine={false} tickLine={false} width={52} />
              <Tooltip content={<CustomTooltip dateFormatter={tooltipFmt} />} />
              {seriesKeys.map(sk => (
                <Area key={sk.key} type="monotone" dataKey={sk.key} stroke={sk.color}
                  fill={`url(#brief-grad-${kpiId}-${sk.key.replace(/\W/g, '_')})`}
                  strokeWidth={2} dot={false} activeDot={{ r: 3, strokeWidth: 2, fill: '#fff' }} />
              ))}
            </AreaChart>
          )}
        </ResponsiveContainer>
        {seriesKeys.length > 1 && (
          <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 pt-1 text-[10px]">
            {seriesKeys.map(sk => (
              <div key={sk.key} className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: sk.color }} />
                <span className="text-slate-500">{sk.key}</span>
              </div>
            ))}
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
