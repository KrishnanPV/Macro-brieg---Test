import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  RotateCcw, ChevronDown, ChevronRight, Search,
  LayoutGrid, LayoutList, Lightbulb, BarChart3, Globe2,
} from 'lucide-react'
import useDataStore from '../../stores/dataStore'
import KpiCard from './KpiCard'

const REGIONS = [
  { label: 'GCC', codes: ['SAU', 'ARE', 'QAT', 'KWT', 'BHR', 'OMN'] },
  { label: 'Americas', codes: ['USA', 'BRA', 'MEX'] },
  { label: 'Europe', codes: ['GBR', 'DEU', 'FRA'] },
  { label: 'Asia-Pacific', codes: ['JPN', 'CHN', 'IND', 'IDN'] },
  { label: 'Africa & ME', codes: ['EGY', 'ZAF', 'NGA', 'TUR'] },
]

const COUNTRY_NAMES = {
  SAU: 'Saudi Arabia', ARE: 'UAE', QAT: 'Qatar',
  KWT: 'Kuwait', BHR: 'Bahrain', OMN: 'Oman',
  USA: 'United States', GBR: 'United Kingdom', DEU: 'Germany',
  FRA: 'France', JPN: 'Japan', CHN: 'China',
  IND: 'India', BRA: 'Brazil', EGY: 'Egypt',
  ZAF: 'South Africa', NGA: 'Nigeria', TUR: 'Turkey',
  IDN: 'Indonesia', MEX: 'Mexico',
}

function orderResultsByKpiCatalog(results, kpis) {
  if (!results.length) return results
  const idx = new Map(kpis.map((k, i) => [String(k.id), i]))
  return [...results].sort((a, b) => {
    const oa = idx.get(String(a.kpi_id)) ?? 9999
    const ob = idx.get(String(b.kpi_id)) ?? 9999
    return oa - ob
  })
}

function CollapsibleSection({ title, defaultOpen = true, count, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between mb-3 pb-1.5 border-b border-slate-100 group"
      >
        <h2 className="text-[11px] font-semibold text-mck-navy uppercase tracking-wider flex items-center gap-1.5">
          {title}
          {count != null && (
            <span className="text-[10px] font-medium text-white bg-mck-deep rounded-full px-1.5 py-0.5 normal-case tracking-normal">{count}</span>
          )}
        </h2>
        <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform duration-200 ${open ? '' : '-rotate-90'}`} />
      </button>
      {open && children}
    </section>
  )
}

export default function Dashboard() {
  const {
    kpis, selectedCountries, selectedKpis, results, loading, error,
    startYear, endYear, countryOptions,
    insightCache, setInsightCache, clearInsightCache,
    fetchKpis, toggleCountry, toggleKpi, setStartYear, setEndYear,
    fetchData, refetchKpi,
  } = useDataStore()

  const [kpiSearch, setKpiSearch] = useState('')
  const [layout, setLayout] = useState('stack')
  const [refetchingKpiId, setRefetchingKpiId] = useState(null)

  useEffect(() => { fetchKpis() }, [fetchKpis])

  const handleResetPage = useCallback(() => {
    useDataStore.setState({ results: [], insightCache: {}, error: '', kpiFrequencies: {} })
  }, [])

  const handleKpiChartFrequencyChange = useCallback(async (kpiId, freq) => {
    if (refetchingKpiId != null) return
    const current = results.find(r => String(r.kpi_id) === String(kpiId))
    if (current && current.frequency === freq) return
    setRefetchingKpiId(kpiId)
    try {
      await refetchKpi(kpiId, freq)
    } catch (e) {
      useDataStore.setState({ error: e.message || String(e) })
    } finally {
      setRefetchingKpiId(null)
    }
  }, [results, refetchKpi, refetchingKpiId])

  const handleSelectAll = useCallback(() => {
    const available = kpis.filter(k => k.available).map(k => k.id)
    useDataStore.setState({ selectedKpis: available })
  }, [kpis])

  const handleDeselectAll = useCallback(() => {
    useDataStore.setState({ selectedKpis: [] })
  }, [])

  const filteredKpis = useMemo(() => {
    if (!kpiSearch.trim()) return kpis
    const q = kpiSearch.toLowerCase()
    return kpis.filter(k =>
      k.name.toLowerCase().includes(q) ||
      String(k.id).includes(q)
    )
  }, [kpis, kpiSearch])

  const ordered = orderResultsByKpiCatalog(results, kpis)
  const insightCount = Object.keys(insightCache).length

  return (
    <div className="flex h-full">
      {/* ─── Sidebar ─── */}
      <aside className="w-72 shrink-0 border-r border-slate-200 bg-white flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">

          {/* Countries */}
          <CollapsibleSection title="Countries" count={selectedCountries.length}>
            <div className="space-y-3">
              {REGIONS.map(region => (
                <div key={region.label}>
                  <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">{region.label}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {region.codes.filter(c => countryOptions.includes(c)).map(code => {
                      const sel = selectedCountries.includes(code)
                      return (
                        <button key={code} type="button" onClick={() => toggleCountry(code)}
                          className={`px-2.5 py-1.5 rounded-md text-[11px] font-medium transition-all duration-150
                            ${sel
                              ? 'bg-mck-navy text-white'
                              : 'bg-slate-50 text-slate-600 hover:bg-slate-100 border border-slate-200'}`}
                          title={COUNTRY_NAMES[code]}
                        >{code}</button>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          </CollapsibleSection>

          {/* KPIs */}
          <CollapsibleSection title="KPIs" count={selectedKpis.length}>
            <div className="space-y-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                <input
                  type="text"
                  value={kpiSearch}
                  onChange={e => setKpiSearch(e.target.value)}
                  placeholder="Search KPIs…"
                  className="w-full pl-8 pr-3 py-1.5 rounded-md border border-slate-200 text-xs text-slate-700 placeholder:text-slate-400 focus:border-mck-deep focus:ring-1 focus:ring-mck-deep/30 outline-none"
                />
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={handleSelectAll}
                  className="text-[10px] font-medium text-mck-deep hover:text-mck-navy transition">Select all</button>
                <span className="text-slate-300">|</span>
                <button type="button" onClick={handleDeselectAll}
                  className="text-[10px] font-medium text-slate-500 hover:text-slate-700 transition">Clear</button>
              </div>
              <div className="space-y-0.5 max-h-64 overflow-y-auto pr-1">
                {filteredKpis.map(k => (
                  <label key={k.id}
                    className={`flex items-start gap-2.5 px-2.5 py-2 rounded-md cursor-pointer transition-all
                      ${!k.available ? 'opacity-40 cursor-not-allowed' : selectedKpis.includes(k.id) ? 'border-l-2 border-l-mck-deep bg-slate-50/60' : 'border-l-2 border-l-transparent hover:bg-slate-50'}`}
                  >
                    <input type="checkbox" disabled={!k.available} checked={selectedKpis.includes(k.id)} onChange={() => toggleKpi(k.id)}
                      className="mt-0.5 accent-mck-deep rounded" />
                    <span className="text-xs leading-snug text-slate-600">
                      <span className="font-semibold text-slate-700">{k.id}.</span> {k.name}
                      {!k.available && <span className="text-red-400 ml-1 italic text-[10px]">(unavailable)</span>}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          </CollapsibleSection>

          {/* Time Range */}
          <CollapsibleSection title="Time Range">
            <div className="flex items-center gap-2">
              <div className="flex-1">
                <label className="text-[10px] text-slate-400 mb-0.5 block">From</label>
                <input type="number" min={1990} max={endYear} value={startYear}
                  onChange={e => { const v = parseInt(e.target.value, 10); if (!isNaN(v)) setStartYear(v) }}
                  className="w-full rounded-md border border-slate-200 px-2.5 py-2 text-xs text-slate-700 focus:border-mck-deep focus:ring-1 focus:ring-mck-deep/30 outline-none tabular-nums" />
              </div>
              <span className="text-slate-300 mt-4">—</span>
              <div className="flex-1">
                <label className="text-[10px] text-slate-400 mb-0.5 block">To</label>
                <input type="number" min={startYear} max={new Date().getFullYear() + 5} value={endYear}
                  onChange={e => { const v = parseInt(e.target.value, 10); if (!isNaN(v)) setEndYear(v) }}
                  className="w-full rounded-md border border-slate-200 px-2.5 py-2 text-xs text-slate-700 focus:border-mck-deep focus:ring-1 focus:ring-mck-deep/30 outline-none tabular-nums" />
              </div>
            </div>
          </CollapsibleSection>
        </div>

        {/* Sticky load button */}
        <div className="px-4 py-4 border-t border-slate-100 bg-white">
          <button onClick={fetchData} disabled={loading}
            className="w-full bg-mck-navy text-white font-semibold py-2.5 rounded-lg hover:bg-mck-deep active:bg-mck-navy disabled:opacity-50 transition-all text-sm">
            {loading ? (
              <span className="inline-flex items-center gap-2">
                <span className="h-3.5 w-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                Loading…
              </span>
            ) : 'Load / Refresh Data'}
          </button>
        </div>
      </aside>

      {/* ─── Main content ─── */}
      <main className="flex-1 overflow-y-auto bg-slate-50/50">
        {error && (
          <div className="mx-6 mt-4 rounded-xl bg-red-50 border border-red-200 text-red-700 px-4 py-3 text-xs">{error}</div>
        )}

        {results.length === 0 && !loading && !error && (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-3">
            <BarChart3 className="w-10 h-10 text-slate-300" />
            <p className="text-sm">Select countries and KPIs, then click <strong>Load / Refresh Data</strong>.</p>
          </div>
        )}

        {results.length > 0 && (
          <div className="px-6 pt-5 pb-6 space-y-5">
            {/* Summary bar */}
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div className="flex items-center gap-5 flex-wrap">
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <BarChart3 className="w-4 h-4 text-mck-deep" />
                  <span><strong className="text-mck-navy">{ordered.length}</strong> KPIs</span>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <Globe2 className="w-4 h-4 text-mck-deep" />
                  <span><strong className="text-mck-navy">{selectedCountries.length}</strong> countries</span>
                </div>
                {insightCount > 0 && (
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <Lightbulb className="w-4 h-4 text-mck-deep" />
                    <span><strong className="text-mck-navy">{insightCount}</strong> insights</span>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2">
                <div className="inline-flex rounded-lg border border-slate-200 overflow-hidden">
                  <button type="button" onClick={() => setLayout('stack')}
                    className={`p-1.5 transition ${layout === 'stack' ? 'bg-mck-navy text-white' : 'bg-white text-slate-400 hover:text-slate-600'}`}
                    title="Stack view">
                    <LayoutList className="w-4 h-4" />
                  </button>
                  <button type="button" onClick={() => setLayout('grid')}
                    className={`p-1.5 transition border-l border-slate-200 ${layout === 'grid' ? 'bg-mck-navy text-white' : 'bg-white text-slate-400 hover:text-slate-600'}`}
                    title="Grid view">
                    <LayoutGrid className="w-4 h-4" />
                  </button>
                </div>
                <button onClick={handleResetPage}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:text-slate-700 transition">
                  <RotateCcw className="w-3.5 h-3.5" />Reset
                </button>
              </div>
            </div>

            {/* KPI cards */}
            <div className={layout === 'grid'
              ? 'grid grid-cols-1 xl:grid-cols-2 gap-5'
              : 'space-y-5'
            }>
              {ordered.map(r => (
                <KpiCard
                  key={r.kpi_id}
                  result={r}
                  countries={selectedCountries}
                  insightCache={insightCache}
                  onInsightCached={setInsightCache}
                  compact={layout === 'grid'}
                  onChartFrequencyChange={handleKpiChartFrequencyChange}
                  chartFrequencyLoading={String(refetchingKpiId) === String(r.kpi_id)}
                />
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
