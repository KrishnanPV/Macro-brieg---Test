import { create } from 'zustand'

const COUNTRY_OPTIONS = [
  'SAU', 'ARE', 'QAT', 'KWT', 'BHR', 'OMN',
  'USA', 'GBR', 'DEU', 'FRA', 'JPN', 'CHN', 'IND', 'BRA',
  'EGY', 'ZAF', 'NGA', 'TUR', 'IDN', 'MEX',
]

const CURRENT_YEAR = new Date().getFullYear()

const useDataStore = create((set, get) => ({
  kpis: [],
  selectedCountries: ['SAU'],
  selectedKpis: [],
  results: [],
  loading: false,
  error: '',
  startYear: 2015,
  endYear: CURRENT_YEAR,
  /** Per-KPI chart resolution on Dashboard (id → 'A' | 'Q'). Missing ids default to annual. */
  kpiFrequencies: {},
  countryOptions: COUNTRY_OPTIONS,
  insightCache: {},

  setInsightCache: (key, payload) => set(s => {
    const normalized = typeof payload === 'string'
      ? { text: payload, newsCatalog: [] }
      : (payload && typeof payload === 'object' ? payload : { text: '', newsCatalog: [] })
    return { insightCache: { ...s.insightCache, [key]: normalized } }
  }),

  clearInsightCache: () => set({ insightCache: {} }),

  fetchKpis: async () => {
    try {
      const resp = await fetch('/api/kpis')
      const data = await resp.json()
      set({ kpis: data })
    } catch {
      set({ error: 'Could not load KPI list — is the backend running?' })
    }
  },

  hydrateFromWorkspace: (ws) => {
    if (!ws) return
    const countries = ws.countries?.length ? ws.countries : ['SAU']
    const kpis = ws.kpi_ids || []
    set({
      selectedCountries: countries, selectedKpis: kpis, results: [], error: '', insightCache: {},
      kpiFrequencies: {},
    })
  },

  toggleCountry: (code) => {
    set(s => ({
      selectedCountries: s.selectedCountries.includes(code)
        ? s.selectedCountries.filter(c => c !== code)
        : [...s.selectedCountries, code],
    }))
  },

  toggleKpi: (id) => {
    set(s => ({
      selectedKpis: s.selectedKpis.includes(id)
        ? s.selectedKpis.filter(k => k !== id)
        : [...s.selectedKpis, id],
    }))
  },

  setStartYear: (y) => set({ startYear: y }),
  setEndYear: (y) => set({ endYear: y }),
  setError: (e) => set({ error: e }),

  fetchData: async () => {
    const { selectedCountries, selectedKpis, startYear, endYear, kpiFrequencies } = get()
    if (!selectedCountries.length) {
      set({ error: 'Select at least one country.' })
      return
    }
    if (!selectedKpis.length) {
      set({ error: 'Select at least one KPI.' })
      return
    }
    set({ error: '', loading: true })
    try {
      const resp = await fetch('/api/fetch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          countries: selectedCountries,
          kpi_ids: selectedKpis,
          timerange_q: `${startYear}-${endYear}`,
          timerange_a: `${startYear}-${endYear}`,
          frequency_overrides: Object.fromEntries(
            selectedKpis.map((id) => [String(id), kpiFrequencies[String(id)] ?? 'A']),
          ),
        }),
      })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${resp.status}`)
      }
      const data = await resp.json()
      set({ results: data.results, loading: false })
    } catch (e) {
      set({ error: e.message, loading: false })
    }
  },

  refetchKpi: async (kpiId, frequency) => {
    const { selectedCountries, startYear, endYear } = get()
    const resp = await fetch('/api/fetch-kpi', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        countries: selectedCountries,
        kpi_id: kpiId,
        frequency,
        timerange_q: `${startYear}-${endYear}`,
        timerange_a: `${startYear}-${endYear}`,
      }),
    })
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}))
      throw new Error(body.detail || `HTTP ${resp.status}`)
    }
    const newResult = await resp.json()
    set(s => ({
      results: s.results.map(r => String(r.kpi_id) === String(kpiId) ? newResult : r),
      kpiFrequencies: { ...s.kpiFrequencies, [String(kpiId)]: frequency },
    }))
  },
}))

export default useDataStore
