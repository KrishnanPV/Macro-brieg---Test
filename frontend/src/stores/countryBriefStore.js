import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

const COUNTRY_OPTIONS = [
  'SAU', 'ARE', 'QAT', 'KWT', 'BHR', 'OMN',
  'USA', 'GBR', 'DEU', 'FRA', 'JPN', 'CHN', 'IND', 'BRA',
  'EGY', 'ZAF', 'NGA', 'TUR', 'IDN', 'MEX',
]

const COUNTRY_NAMES = {
  SAU: 'Saudi Arabia', ARE: 'United Arab Emirates', QAT: 'Qatar',
  KWT: 'Kuwait', BHR: 'Bahrain', OMN: 'Oman',
  USA: 'United States', GBR: 'United Kingdom', DEU: 'Germany',
  FRA: 'France', JPN: 'Japan', CHN: 'China',
  IND: 'India', BRA: 'Brazil', EGY: 'Egypt',
  ZAF: 'South Africa', NGA: 'Nigeria', TUR: 'Turkey',
  IDN: 'Indonesia', MEX: 'Mexico',
}

const CURRENT_YEAR = new Date().getFullYear()

const useCountryBriefStore = create(
  persist(
    (set, get) => ({
      // --- Country / time selection ---
      countryOptions: COUNTRY_OPTIONS,
      countryNames: COUNTRY_NAMES,
      /** Active workspace scope — used to invalidate cached brief when switching workspaces */
      workspaceId: null,
      selectedCountry: null,
      startYear: 2015,
      endYear: CURRENT_YEAR,
      focus: '',
      // --- KPI selection ---
      /** 'auto' = backend picks KPIs; 'manual' = user picks from list */
      kpiSelectionMode: 'auto',
      /** Full KPI catalogue from /api/kpis */
      kpiCatalog: [],
      /** User-selected KPI ids when mode is 'manual' */
      selectedKpiIds: [],

      // --- Generation state ---
      generating: false,
      statusMessage: '',
      streamingText: '',
      blocks: [],
      kpiDataCache: [],
      fdiBenchmark: null,
      fdiBenchmarkCacheKey: null,
      fdiFlowMode: 'chart',
      triageResults: [],
      error: '',
      briefGenerated: false,
      /** Newscatcher articles for [src:N] markers (same order as backend catalog). */
      newsArticles: [],

      // --- Debug mode (not persisted) ---
      debugMode: false,

      // --- Sidebar chat state ---
      sidebarOpen: false,
      activeSectionIndex: null,
      activeSectionTitle: '',
      activeSectionContent: '',
      sidebarHistory: {},

      // --- Setters ---
      setSelectedCountry: (code) => set({
        selectedCountry: code, briefGenerated: false, blocks: [],
        kpiDataCache: [], fdiBenchmark: null, fdiBenchmarkCacheKey: null, fdiFlowMode: 'chart',
        triageResults: [], error: '', streamingText: '',
        newsArticles: [],
        sidebarOpen: false, activeSectionIndex: null, sidebarHistory: {},
      }),
      setStartYear: (y) => set({ startYear: y }),
      setEndYear: (y) => set({ endYear: y }),
      setFocus: (f) => set({ focus: f }),
      setError: (e) => set({ error: e }),
      setFdiFlowMode: (mode) => set({
        fdiFlowMode: ['chart', 'inflow', 'outflow'].includes(mode) ? mode : 'chart',
      }),
      refreshFdiBenchmark: async (startYear, endYear) => {
        const { fdiBenchmarkCacheKey } = get()
        if (!fdiBenchmarkCacheKey) {
          set({ error: 'FDI benchmark cache unavailable. Regenerate the brief.' })
          return null
        }
        if (startYear >= endYear) {
          set({ error: 'Start year must be earlier than end year.' })
          return null
        }
        try {
          const resp = await fetch('/api/country-brief/fdi-benchmark', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              benchmark_cache_key: fdiBenchmarkCacheKey,
              start_year: startYear,
              end_year: endYear,
            }),
          })
          if (!resp.ok) {
            const detail = await resp.json().catch(() => ({}))
            throw new Error(detail.detail || `HTTP ${resp.status}`)
          }
          const payload = await resp.json()
          set({
            fdiBenchmark: payload,
            fdiBenchmarkCacheKey: payload?.benchmark_cache_key || fdiBenchmarkCacheKey,
            error: '',
          })
          return payload
        } catch (e) {
          set({ error: e.message || 'Failed to refresh FDI benchmark.' })
          return null
        }
      },
      setKpiSelectionMode: (mode) => set({ kpiSelectionMode: mode }),
      toggleKpiId: (id) => set((s) => {
        const ids = s.selectedKpiIds.includes(id)
          ? s.selectedKpiIds.filter(k => k !== id)
          : [...s.selectedKpiIds, id]
        return { selectedKpiIds: ids }
      }),
      fetchKpiCatalog: async () => {
        if (get().kpiCatalog.length) return
        try {
          const resp = await fetch('/api/kpis')
          const data = await resp.json()
          set({ kpiCatalog: data })
        } catch { /* best-effort */ }
      },

      fetchDebugMode: async () => {
        try {
          const resp = await fetch('/api/debug-mode')
          const data = await resp.json()
          set({ debugMode: !!data.debug })
        } catch { /* best-effort */ }
      },

      storeTestReport: async () => {
        const { selectedCountry, startYear, endYear, focus, blocks, kpiDataCache, fdiBenchmark, triageResults, newsArticles } = get()
        try {
          const resp = await fetch('/api/country-brief/test-report/store', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              country: selectedCountry,
              startYear,
              endYear,
              focus,
              blocks,
              kpiDataCache,
              fdiBenchmark,
              triageResults,
              newsArticles,
            }),
          })
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
          set({ error: '' })
          return true
        } catch (e) {
          set({ error: e.message || 'Failed to store test report.' })
          return false
        }
      },

      loadTestReport: async () => {
        set({ generating: true, statusMessage: 'Loading test report…', error: '' })
        try {
          const resp = await fetch('/api/country-brief/test-report/load')
          if (!resp.ok) {
            const detail = await resp.json().catch(() => ({}))
            throw new Error(detail.detail || `HTTP ${resp.status}`)
          }
          const data = await resp.json()
          set({
            selectedCountry: data.country,
            startYear: data.startYear,
            endYear: data.endYear,
            focus: data.focus || '',
            blocks: data.blocks,
            kpiDataCache: data.kpiDataCache || [],
            fdiBenchmark: data.fdiBenchmark || null,
            fdiBenchmarkCacheKey: data.fdiBenchmark?.benchmark_cache_key || null,
            triageResults: data.triageResults || [],
            newsArticles: data.newsArticles || [],
            briefGenerated: true,
            generating: false,
            statusMessage: '',
            streamingText: '',
            sidebarOpen: false,
            sidebarHistory: {},
          })
        } catch (e) {
          set({ error: e.message, generating: false, statusMessage: '' })
        }
      },

      resetBrief: () => set({
        selectedCountry: null, briefGenerated: false, blocks: [],
        kpiDataCache: [], fdiBenchmark: null, fdiBenchmarkCacheKey: null, fdiFlowMode: 'chart',
        triageResults: [], error: '', focus: '',
        streamingText: '', statusMessage: '', generating: false,
        newsArticles: [],
        sidebarOpen: false, activeSectionIndex: null, sidebarHistory: {},
        workspaceId: get().workspaceId,
        kpiSelectionMode: 'auto',
        selectedKpiIds: [],
      }),

      /**
       * Merge server workspace `country_brief` with client state.
       * Preserves generated blocks when the same workspace + country + range + focus still match
       * (so navigation away / tab refresh does not wipe the brief).
       * Clears when switching workspace or when server selection no longer matches a client brief.
       */
      hydrateFromWorkspace: (brief, workspaceId) => set((s) => {
        const nextWs = workspaceId ?? null
        const prevWs = s.workspaceId

        if (prevWs != null && nextWs != null && prevWs !== nextWs) {
          return {
            workspaceId: nextWs,
            selectedCountry: brief?.country ?? null,
            startYear: brief?.startYear ?? 2015,
            endYear: brief?.endYear ?? CURRENT_YEAR,
            focus: brief?.focus ?? '',
            blocks: [],
            kpiDataCache: [],
            fdiBenchmark: null,
            fdiBenchmarkCacheKey: null,
            fdiFlowMode: 'chart',
            triageResults: [],
            briefGenerated: false,
            error: '',
            streamingText: '',
            newsArticles: [],
            sidebarHistory: {},
            sidebarOpen: false,
          }
        }

        if (!brief || !brief.country) {
          return { workspaceId: nextWs ?? prevWs }
        }

        const country = brief.country
        const startYear = brief.startYear || 2015
        const endYear = brief.endYear || CURRENT_YEAR
        const focus = brief.focus || ''

        const sameAsServer =
          s.selectedCountry === country &&
          s.startYear === startYear &&
          s.endYear === endYear &&
          (s.focus || '') === focus

        const keepClient =
          s.briefGenerated &&
          sameAsServer &&
          Array.isArray(s.blocks) &&
          s.blocks.length > 0

        if (keepClient) {
          return { workspaceId: nextWs ?? prevWs }
        }

        return {
          workspaceId: nextWs ?? prevWs,
          selectedCountry: country,
          startYear,
          endYear,
          focus,
          blocks: [],
          kpiDataCache: [],
          fdiBenchmark: null,
          fdiBenchmarkCacheKey: null,
          fdiFlowMode: 'chart',
          triageResults: [],
          briefGenerated: false,
          error: '',
          streamingText: '',
          newsArticles: [],
          sidebarHistory: {},
        }
      }),

      // --- Brief generation (streaming) ---
      generateBrief: async () => {
        const { selectedCountry, startYear, endYear, focus, kpiSelectionMode, selectedKpiIds } = get()
        if (!selectedCountry) {
          set({ error: 'Select a country.' })
          return
        }
        if (kpiSelectionMode === 'manual' && selectedKpiIds.length === 0) {
          set({ error: 'Select at least one KPI, or switch to automatic selection.' })
          return
        }

        set({
          generating: true, error: '', blocks: [], kpiDataCache: [],
          fdiBenchmark: null, fdiBenchmarkCacheKey: null, fdiFlowMode: 'chart',
          triageResults: [], streamingText: '', statusMessage: 'Starting...',
          briefGenerated: false, newsArticles: [], sidebarOpen: false, sidebarHistory: {},
        })

        const payload = {
          country: selectedCountry,
          start_year: startYear,
          end_year: endYear,
          focus: focus || null,
          deep_analysis: true,
        }
        if (kpiSelectionMode === 'manual') {
          payload.kpi_ids = selectedKpiIds
        }

        try {
          const resp = await fetch('/api/country-brief/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          })

          if (!resp.ok) {
            const detail = await resp.json().catch(() => ({}))
            throw new Error(detail.detail || `HTTP ${resp.status}`)
          }

          const reader = resp.body.getReader()
          const decoder = new TextDecoder()
          let lineBuf = ''
          let fullText = ''

          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            lineBuf += decoder.decode(value, { stream: true })
            const lines = lineBuf.split('\n')
            lineBuf = lines.pop() ?? ''

            for (const line of lines) {
              const trimmed = line.trim()
              if (!trimmed) continue
              try {
                const chunk = JSON.parse(trimmed)

                if (chunk.type === 'status') {
                  set({ statusMessage: chunk.content })
                } else if (chunk.type === 'kpi_data') {
                  set({ kpiDataCache: chunk.content })
                } else if (chunk.type === 'fdi_benchmark') {
                  set({
                    fdiBenchmark: chunk.content,
                    fdiBenchmarkCacheKey: chunk.content?.benchmark_cache_key || null,
                  })
                } else if (chunk.type === 'triage') {
                  set({ triageResults: chunk.content })
                } else if (chunk.type === 'news_catalog') {
                  set({ newsArticles: chunk.content?.articles || [] })
                } else if (chunk.type === 'text_delta') {
                  fullText += chunk.content
                  set({ streamingText: fullText })
                } else if (chunk.type === 'blocks') {
                  set({ blocks: chunk.content, briefGenerated: true })
                } else if (chunk.type === 'done') {
                  set({ generating: false, statusMessage: '' })
                }
              } catch { /* malformed chunk */ }
            }
          }

          if (lineBuf.trim()) {
            try {
              const chunk = JSON.parse(lineBuf.trim())
              if (chunk.type === 'blocks') {
                set({ blocks: chunk.content, briefGenerated: true })
              }
            } catch { /* ignore */ }
          }

          set({ generating: false, statusMessage: '' })
        } catch (e) {
          set({ error: e.message, generating: false, statusMessage: '' })
        }
      },

      // --- Sidebar ---
      openSidebar: (sectionIndex, sectionTitle, sectionContent) => set({
        sidebarOpen: true,
        activeSectionIndex: sectionIndex,
        activeSectionTitle: sectionTitle,
        activeSectionContent: sectionContent,
      }),

      closeSidebar: () => set({
        sidebarOpen: false,
        activeSectionIndex: null,
        activeSectionTitle: '',
        activeSectionContent: '',
      }),

      addSidebarMessage: (sectionIndex, role, content) => set(s => {
        const key = String(sectionIndex)
        const history = { ...s.sidebarHistory }
        if (!history[key]) history[key] = []
        history[key] = [...history[key], { role, content }]
        return { sidebarHistory: history }
      }),

      updateBlockContent: (sectionIndex, newContent) => set(s => {
        const blocks = [...s.blocks]
        const block = blocks[sectionIndex]
        if (!block) return {}

        if (block.type === 'section') {
          blocks[sectionIndex] = {
            ...block,
            children: [{ type: 'narrative', content: newContent }],
          }
        } else if (block.type === 'executive_summary' || block.type === 'outlook') {
          blocks[sectionIndex] = { ...block, content: newContent }
        }

        return { blocks, activeSectionContent: newContent }
      }),
    }),
    {
      name: 'macrobrief-country-brief',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        workspaceId: state.workspaceId,
        selectedCountry: state.selectedCountry,
        startYear: state.startYear,
        endYear: state.endYear,
        focus: state.focus,
        blocks: state.blocks,
        kpiDataCache: state.kpiDataCache,
        fdiBenchmark: state.fdiBenchmark,
        fdiBenchmarkCacheKey: state.fdiBenchmarkCacheKey,
        fdiFlowMode: state.fdiFlowMode,
        triageResults: state.triageResults,
        briefGenerated: state.briefGenerated,
        newsArticles: state.newsArticles,
        sidebarHistory: state.sidebarHistory,
      }),
    }
  )
)

export default useCountryBriefStore
