import { useMemo } from 'react'
import { formatAbbrevNumber } from '../../../lib/formatNumbers'

function formatCagr(cagr) {
  if (cagr == null) return 'n/a'
  const pct = (cagr * 100).toFixed(1)
  return `${cagr >= 0 ? '+' : ''}${pct}%`
}

function bucketBarColor(bucket) {
  if (bucket === 'target') return 'bg-mck-navy'
  if (bucket === 'global') return 'bg-blue-500'
  return 'bg-cyan-500'
}

function cagrBubbleColor(cagr) {
  if (cagr == null) return 'bg-slate-100 text-slate-500'
  if (cagr < 0) return 'bg-rose-100 text-rose-700'
  return 'bg-emerald-100 text-emerald-700'
}

function resolveCountries(benchmarkData, flowMode) {
  const rows = Array.isArray(benchmarkData?.countries) ? benchmarkData.countries : []
  const byCode = new Map(rows.map(r => [r.country_code, r]))
  const preferred = benchmarkData?.sorted_country_codes?.[flowMode] || []
  const ordered = preferred
    .map(code => byCode.get(code))
    .filter(Boolean)
  if (ordered.length === rows.length) return ordered
  return [...rows].sort((a, b) => {
    const av = a?.[flowMode]?.end
    const bv = b?.[flowMode]?.end
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    return bv - av
  })
}

function BarsColumn({
  title,
  countries,
  flowMode,
  valueKey,
  maxAbsValue,
  showCagrBubble = false,
  cagrHeading = 'CAGR',
}) {
  const gridCols = showCagrBubble
    ? 'grid-cols-[2.5rem_1fr_auto_auto]'
    : 'grid-cols-[2.5rem_1fr_auto]'
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-2.5">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">{title}</p>
      <div className={`grid ${gridCols} items-center gap-2 mb-1`}>
        <span />
        <span />
        <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-wider text-right">Value</span>
        {showCagrBubble ? (
          <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-wider text-center min-w-[2.9rem]">
            {cagrHeading}
          </span>
        ) : null}
      </div>
      <div className="space-y-2.5">
        {countries.map(country => {
          const flow = country?.[flowMode] || {}
          const rawValue = flow[valueKey]
          const value = rawValue == null ? null : Number(rawValue)
          const barWidthPct = value == null ? 0 : Math.max(1, (Math.abs(value) / maxAbsValue) * 100)
          const bucket = country.bucket || 'regional'
          const isTarget = bucket === 'target'
          const cagr = flow.cagr

          return (
            <div
              key={country.country_code}
              className={`space-y-1 rounded-md px-1.5 py-1 ${
                isTarget ? 'bg-blue-50 border border-blue-100' : ''
              }`}
            >
              <div className={`grid ${gridCols} items-center gap-2`}>
                <div className={`text-[10px] font-semibold ${isTarget ? 'text-mck-navy' : 'text-slate-600'}`}>
                  {country.country_code}
                </div>
                <div className="h-3 flex items-center">
                  {value == null ? (
                    <div className="h-0 w-full border-t border-dashed border-slate-300" />
                  ) : (
                    <div
                      className={`h-full ${bucketBarColor(bucket)}`}
                      style={{ width: `${barWidthPct}%`, minWidth: value === 0 ? '0px' : '4px' }}
                      title={`${country.country_name}: ${formatAbbrevNumber(value)}`}
                    />
                  )}
                </div>
                <div className="text-[10px] font-mono text-slate-700 text-right min-w-[3.8rem]">
                  {formatAbbrevNumber(value)}
                </div>
                {showCagrBubble ? (
                  <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold min-w-[2.9rem] text-center ${cagrBubbleColor(cagr)} ${isTarget ? 'ring-1 ring-blue-300' : ''}`}>
                    {formatCagr(cagr)}
                  </span>
                ) : null}
              </div>
              <div className={`text-[10px] pl-[2.5rem] truncate ${isTarget ? 'text-slate-700 font-medium' : 'text-slate-500'}`}>
                {country.country_name}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function FdiBenchmarkChart({
  benchmarkData,
  flowMode = 'inflow',
  onFlowModeChange,
}) {
  const countries = useMemo(
    () => resolveCountries(benchmarkData, flowMode),
    [benchmarkData, flowMode],
  )
  if (!countries.length) return null

  const maxAbsValue = Math.max(
    1,
    ...countries.flatMap(country => {
      const flow = country?.[flowMode] || {}
      return [Math.abs(flow.start || 0), Math.abs(flow.end || 0)]
    }),
  )
  const startYear = benchmarkData?.start_year
  const endYear = benchmarkData?.end_year
  const unit = benchmarkData?.unit || ''

  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-100">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              FDI Benchmark (Start vs End Year)
            </p>
            {unit ? <p className="text-[10px] text-slate-400 mt-0.5">{unit}</p> : null}
          </div>
          <div className="inline-flex rounded-lg border border-slate-200 overflow-hidden">
            <button
              type="button"
              onClick={() => onFlowModeChange?.('inflow')}
              className={`px-2 py-1 text-[11px] font-medium transition-all ${
                flowMode === 'inflow' ? 'bg-mck-navy text-white' : 'bg-white text-slate-500 hover:bg-slate-50'
              }`}
            >
              Inflow
            </button>
            <button
              type="button"
              onClick={() => onFlowModeChange?.('outflow')}
              className={`px-2 py-1 text-[11px] font-medium transition-all border-l border-slate-200 ${
                flowMode === 'outflow' ? 'bg-mck-navy text-white' : 'bg-white text-slate-500 hover:bg-slate-50'
              }`}
            >
              Outflow
            </button>
          </div>
        </div>
      </div>

      <div className="p-2.5 grid grid-cols-1 md:grid-cols-2 gap-2.5">
        <BarsColumn
          title={`${startYear}`}
          countries={countries}
          flowMode={flowMode}
          valueKey="start"
          maxAbsValue={maxAbsValue}
        />
        <BarsColumn
          title={`${endYear}`}
          countries={countries}
          flowMode={flowMode}
          valueKey="end"
          maxAbsValue={maxAbsValue}
          showCagrBubble
          cagrHeading="CAGR"
        />
      </div>
    </div>
  )
}
