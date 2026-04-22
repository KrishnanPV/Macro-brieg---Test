import { useEffect, useMemo, useState } from 'react'
import { formatAbbrevNumber } from '../../../lib/formatNumbers'

function formatCagr(cagr) {
  if (cagr == null) return 'n/a'
  const pct = (cagr * 100).toFixed(1)
  return `${cagr >= 0 ? '+' : ''}${pct}%`
}

function formatValue(value) {
  if (value == null) return 'n/a'
  return formatAbbrevNumber(Number(value))
}

function cagrBubbleColor(cagr) {
  if (cagr == null) return 'bg-slate-100 text-slate-500'
  if (cagr < 0) return 'bg-rose-100 text-rose-700'
  return 'bg-emerald-100 text-emerald-700'
}

function bucketBarColor(bucket) {
  if (bucket === 'target') return 'bg-mck-navy'
  if (bucket === 'global') return 'bg-blue-500'
  return 'bg-cyan-500'
}

function resolveCountries(benchmarkData, flowMode) {
  const normalizedFlow = flowMode === 'outflow' ? 'outflow' : 'inflow'
  const rows = Array.isArray(benchmarkData?.countries) ? benchmarkData.countries : []
  const byCode = new Map(rows.map(r => [r.country_code, r]))
  const preferred = benchmarkData?.sorted_country_codes?.[normalizedFlow] || []
  const ordered = preferred
    .map(code => byCode.get(code))
    .filter(Boolean)
  if (ordered.length === rows.length) return ordered
  return [...rows].sort((a, b) => {
    const av = a?.[normalizedFlow]?.end
    const bv = b?.[normalizedFlow]?.end
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    return bv - av
  })
}

export default function FdiBenchmarkChart({
  benchmarkData,
  flowMode = 'inflow',
  onFlowModeChange,
  onYearRangeChange,
}) {
  const normalizedFlow = flowMode === 'outflow' ? 'outflow' : 'inflow'
  const countries = useMemo(
    () => resolveCountries(benchmarkData, normalizedFlow),
    [benchmarkData, normalizedFlow],
  )
  if (!countries.length) return null

  const startYear = Number(benchmarkData?.start_year)
  const endYear = Number(benchmarkData?.end_year)
  const rawMinYear = Number(benchmarkData?.min_year)
  const rawMaxYear = Number(benchmarkData?.max_year)
  const minYear = Number.isFinite(rawMinYear) ? rawMinYear : startYear
  const maxYear = Number.isFinite(rawMaxYear) ? rawMaxYear : endYear
  const lowerBound = Math.min(minYear, maxYear)
  const upperBound = Math.max(minYear, maxYear)
  const [selectedStartYear, setSelectedStartYear] = useState(startYear)
  const [selectedEndYear, setSelectedEndYear] = useState(endYear)
  const [refreshingYears, setRefreshingYears] = useState(false)

  useEffect(() => {
    setSelectedStartYear(startYear)
    setSelectedEndYear(endYear)
  }, [startYear, endYear])

  const yearOptions = useMemo(() => {
    const years = []
    for (let year = lowerBound; year <= upperBound; year += 1) {
      years.push(year)
    }
    return years
  }, [lowerBound, upperBound])

  const startYearOptions = yearOptions.filter(year => year < selectedEndYear)
  const endYearOptions = yearOptions.filter(year => year > selectedStartYear)
  const unit = benchmarkData?.unit || ''
  const flowLabel = normalizedFlow === 'outflow' ? 'Outflow' : 'Inflow'
  const maxAbsValue = Math.max(
    1,
    ...countries.flatMap(country => {
      const flow = country?.[normalizedFlow] || {}
      return [Math.abs(flow.start || 0), Math.abs(flow.end || 0)]
    }),
  )

  const handleStartYearChange = async (event) => {
    const nextYear = Number(event.target.value)
    if (!Number.isFinite(nextYear) || nextYear >= selectedEndYear) return
    const prevYear = selectedStartYear
    setSelectedStartYear(nextYear)
    if (!onYearRangeChange) return
    setRefreshingYears(true)
    const updated = await onYearRangeChange(nextYear, selectedEndYear)
    if (!updated) {
      setSelectedStartYear(prevYear)
    }
    setRefreshingYears(false)
  }

  const handleEndYearChange = async (event) => {
    const nextYear = Number(event.target.value)
    if (!Number.isFinite(nextYear) || nextYear <= selectedStartYear) return
    const prevYear = selectedEndYear
    setSelectedEndYear(nextYear)
    if (!onYearRangeChange) return
    setRefreshingYears(true)
    const updated = await onYearRangeChange(selectedStartYear, nextYear)
    if (!updated) {
      setSelectedEndYear(prevYear)
    }
    setRefreshingYears(false)
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-100">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              FDI {flowLabel} Benchmark
            </p>
            {unit ? <p className="text-[10px] text-slate-400 mt-0.5">{unit}</p> : null}
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <div className="inline-flex items-center rounded-lg border border-slate-200 bg-white px-2 py-1">
              <span className="text-[10px] font-medium text-slate-400 mr-1">Start</span>
              <select
                value={selectedStartYear}
                onChange={handleStartYearChange}
                disabled={refreshingYears}
                className="bg-transparent text-[11px] font-medium text-slate-600 outline-none"
              >
                {startYearOptions.map(year => (
                  <option key={`start-${year}`} value={year}>{year}</option>
                ))}
              </select>
            </div>
            <div className="inline-flex items-center rounded-lg border border-slate-200 bg-white px-2 py-1">
              <span className="text-[10px] font-medium text-slate-400 mr-1">End</span>
              <select
                value={selectedEndYear}
                onChange={handleEndYearChange}
                disabled={refreshingYears}
                className="bg-transparent text-[11px] font-medium text-slate-600 outline-none"
              >
                {endYearOptions.map(year => (
                  <option key={`end-${year}`} value={year}>{year}</option>
                ))}
              </select>
            </div>
            <div className="inline-flex rounded-lg border border-slate-200 overflow-hidden">
              <button
                type="button"
                onClick={() => onFlowModeChange?.('inflow')}
                className={`px-2 py-1 text-[11px] font-medium transition-all ${
                  normalizedFlow === 'inflow' ? 'bg-mck-navy text-white' : 'bg-white text-slate-500 hover:bg-slate-50'
                }`}
              >
                Inflow
              </button>
              <button
                type="button"
                onClick={() => onFlowModeChange?.('outflow')}
                className={`px-2 py-1 text-[11px] font-medium transition-all border-l border-slate-200 ${
                  normalizedFlow === 'outflow' ? 'bg-mck-navy text-white' : 'bg-white text-slate-500 hover:bg-slate-50'
                }`}
              >
                Outflow
              </button>
            </div>
            <div className="w-px h-4 bg-slate-200 mx-0.5" />
            <button
              type="button"
              onClick={() => onFlowModeChange?.('chart')}
              className="px-2.5 py-1 text-[11px] font-semibold rounded-lg transition-all bg-amber-50 text-amber-700 border border-amber-300 hover:bg-amber-100"
            >
              Chart
            </button>
          </div>
        </div>
      </div>

      <div className="p-2.5">
        <div className="rounded-lg border border-slate-200 overflow-hidden">
          <div className="grid grid-cols-[minmax(8rem,1.5fr)_minmax(5rem,1fr)_minmax(5rem,1fr)_auto] items-center gap-2 bg-slate-50 px-2.5 py-1.5">
            <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-wider">Country</span>
            <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-wider text-right">{startYear}</span>
            <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-wider text-right">{endYear}</span>
            <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-wider text-center min-w-[2.9rem]">CAGR</span>
          </div>
          <div className="divide-y divide-slate-100">
            {countries.map(country => {
              const flow = country?.[normalizedFlow] || {}
              const isTarget = (country.bucket || 'regional') === 'target'
              const startValue = flow.start == null ? null : Number(flow.start)
              const endValue = flow.end == null ? null : Number(flow.end)
              const startBarWidthPct = startValue == null ? 0 : Math.max(1, (Math.abs(startValue) / maxAbsValue) * 100)
              const endBarWidthPct = endValue == null ? 0 : Math.max(1, (Math.abs(endValue) / maxAbsValue) * 100)

              return (
                <div
                  key={country.country_code}
                  className={`grid grid-cols-[minmax(8rem,1.5fr)_minmax(5rem,1fr)_minmax(5rem,1fr)_auto] items-center gap-2 px-2.5 py-2 ${
                    isTarget ? 'bg-blue-50/70' : 'bg-white'
                  }`}
                >
                  <div className="min-w-0">
                    <div className={`text-[10px] font-semibold truncate ${isTarget ? 'text-mck-navy' : 'text-slate-700'}`}>
                      {country.country_name}
                    </div>
                    <div className="text-[9px] text-slate-400">{country.country_code}</div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {startValue == null ? (
                      <div className="flex-1 h-3 border-b border-dashed border-slate-300" />
                    ) : (
                      <div
                        className={`h-3 rounded ${bucketBarColor(country.bucket || 'regional')}`}
                        style={{ width: `${startBarWidthPct}%`, minWidth: startValue === 0 ? '0px' : '4px' }}
                        title={`${country.country_name} ${startYear}: ${formatValue(startValue)}`}
                      />
                    )}
                    <span className="text-[10px] font-mono text-slate-700 whitespace-nowrap">{formatValue(startValue)}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {endValue == null ? (
                      <div className="flex-1 h-3 border-b border-dashed border-slate-300" />
                    ) : (
                      <div
                        className={`h-3 rounded ${bucketBarColor(country.bucket || 'regional')}`}
                        style={{ width: `${endBarWidthPct}%`, minWidth: endValue === 0 ? '0px' : '4px' }}
                        title={`${country.country_name} ${endYear}: ${formatValue(endValue)}`}
                      />
                    )}
                    <span className="text-[10px] font-mono text-slate-700 whitespace-nowrap">{formatValue(endValue)}</span>
                  </div>
                  <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold min-w-[2.9rem] text-center ${cagrBubbleColor(flow.cagr)} ${isTarget ? 'ring-1 ring-blue-300' : ''}`}>
                    {formatCagr(flow.cagr)}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
