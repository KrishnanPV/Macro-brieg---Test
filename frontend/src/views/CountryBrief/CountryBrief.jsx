import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Sparkles, Loader2, RotateCcw, Target, Download, DatabaseBackup, Upload, FileText, ChevronDown, X, Columns3, ScrollText, Menu, Maximize2, Minimize2, BarChart3, ChevronRight, CheckCircle2, XCircle } from 'lucide-react'
import useCountryBriefStore from '../../stores/countryBriefStore'
import MetricsRibbon from './blocks/MetricsRibbon'
import ExecSummaryBlock from './blocks/ExecSummaryBlock'
import NarrativeBlock from './blocks/NarrativeBlock'
import InlineChartBlock from './blocks/InlineChartBlock'
import SectionDivider from './blocks/SectionDivider'
import OutlookBlock from './blocks/OutlookBlock'
import BriefSidebar from './BriefSidebar'
import TriagePanel from './blocks/TriagePanel'

function CountrySelector({ countryOptions, countryNames, selectedCountry, onSelect }) {
  const regions = [
    { label: 'GCC', codes: ['SAU', 'ARE', 'QAT', 'KWT', 'BHR', 'OMN'] },
    { label: 'Americas', codes: ['USA', 'BRA', 'MEX'] },
    { label: 'Europe', codes: ['GBR', 'DEU', 'FRA'] },
    { label: 'Asia-Pacific', codes: ['JPN', 'CHN', 'IND', 'IDN'] },
    { label: 'Africa & Middle East', codes: ['EGY', 'ZAF', 'NGA', 'TUR'] },
  ]

  return (
    <div className="space-y-5">
      {regions.map(region => (
        <div key={region.label}>
          <h3 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">{region.label}</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
            {region.codes.filter(c => countryOptions.includes(c)).map(code => (
              <button
                key={code}
                type="button"
                onClick={() => onSelect(code)}
                className={`
                  relative px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200
                  ${selectedCountry === code
                    ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/25 scale-[1.02]'
                    : 'bg-white text-slate-700 border border-slate-200 hover:border-blue-300 hover:shadow-md hover:scale-[1.01]'
                  }
                `}
              >
                <span className="block text-[11px] font-bold tabular-nums">{code}</span>
                <span className="block text-[10px] mt-0.5 opacity-75 truncate">{countryNames[code]}</span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function StreamingProgress({ statusMessage, streamingText }) {
  return (
    <div className="max-w-4xl mx-auto px-6 py-16">
      <div className="text-center mb-8">
        <div className="inline-flex items-center gap-3 px-6 py-3 bg-gradient-to-r from-indigo-50 to-blue-50 border border-indigo-200/60 rounded-2xl">
          <Loader2 className="w-5 h-5 animate-spin text-indigo-600" />
          <span className="text-sm font-medium text-indigo-700">{statusMessage || 'Generating brief...'}</span>
        </div>
      </div>
      {streamingText && (
        <div className="rounded-2xl border border-slate-200 bg-white shadow-sm p-6 max-h-96 overflow-y-auto">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-3">Preview</p>
          <div className="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap opacity-60">
            {streamingText.slice(-1500)}
          </div>
        </div>
      )}
    </div>
  )
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function collectInlineCssText() {
  let cssText = ''
  for (const sheet of Array.from(document.styleSheets)) {
    try {
      for (const rule of Array.from(sheet.cssRules || [])) {
        cssText += `${rule.cssText}\n`
      }
    } catch {
      // Some browser-managed stylesheets (extensions/cross-origin) are inaccessible.
    }
  }
  return cssText
}

/* ───────────────────────────── Free-scroll (legacy) view ────────────────────────────── */

function FreeScrollDocument({
  blocks,
  kpiDataCache,
  fdiBenchmark,
  fdiFlowMode,
  onFdiFlowModeChange,
  onFdiBenchmarkYearChange,
  onDiscuss,
  newsCatalog = [],
}) {
  const metricsBlock = blocks.find(b => b.type === 'metrics_ribbon')
  const execBlock = blocks.find(b => b.type === 'executive_summary')
  const sectionBlocks = blocks.filter(b => b.type === 'section')
  const outlookBlock = blocks.find(b => b.type === 'outlook')

  const getBlockIndex = (block) => blocks.indexOf(block)

  return (
    <div className="space-y-6">
      {metricsBlock && <MetricsRibbon metrics={metricsBlock.metrics} kpiDataCache={kpiDataCache} />}

      <div className="max-w-5xl mx-auto px-6 py-4 space-y-8">
        {execBlock && (
          <ExecSummaryBlock
            content={execBlock.content}
            blockIndex={getBlockIndex(execBlock)}
            onDiscuss={onDiscuss}
            newsCatalog={newsCatalog}
          />
        )}

        {sectionBlocks.map((section) => {
          const sIdx = getBlockIndex(section)
          const charts = section.children?.filter(c => c.type === 'chart_ref') || []
          const narratives = section.children?.filter(c => c.type === 'narrative') || []

          return (
            <div key={sIdx}>
              <SectionDivider title={section.title} />
              <div className="flex gap-0 mt-2 rounded-2xl border border-slate-200/80 bg-white shadow-sm overflow-hidden items-stretch">
                <div className="min-w-0 flex-1 bg-slate-50/40 p-4 space-y-4 flex flex-col justify-center">
                  {charts.length > 0 ? charts.map((child, cIdx) => (
                    <InlineChartBlock
                      key={cIdx}
                      kpiId={child.kpi_id}
                      kpiDataCache={kpiDataCache}
                      fdiBenchmark={fdiBenchmark}
                      fdiFlowMode={fdiFlowMode}
                      onFdiFlowModeChange={onFdiFlowModeChange}
                      onFdiBenchmarkYearChange={onFdiBenchmarkYearChange}
                      exhibitLabel={child.exhibit_label || null}
                      compact
                    />
                  )) : (
                    <div className="flex items-center justify-center h-48 text-xs text-slate-300">
                      No chart data
                    </div>
                  )}
                </div>
                <div className="w-px bg-slate-200 shrink-0" />
                <div className="min-w-0 shrink-0 w-[min(100%,19rem)] sm:w-[min(100%,20.5rem)] lg:w-[min(100%,22rem)] p-4 lg:p-5 space-y-2 flex flex-col justify-start overflow-y-auto">
                  {narratives.map((child, cIdx) => (
                    <NarrativeBlock
                      key={cIdx}
                      variant="insights"
                      content={child.content}
                      blockIndex={cIdx}
                      sectionIndex={sIdx}
                      sectionTitle={section.title}
                      onDiscuss={onDiscuss}
                      newsCatalog={newsCatalog}
                    />
                  ))}
                </div>
              </div>
            </div>
          )
        })}

        {outlookBlock && (
          <>
            <SectionDivider title="Forward Outlook" />
            <OutlookBlock
              content={outlookBlock.content}
              blockIndex={getBlockIndex(outlookBlock)}
              onDiscuss={onDiscuss}
              newsCatalog={newsCatalog}
            />
          </>
        )}
      </div>
    </div>
  )
}

/* ────────────────────────────── Executive Summary Modal ─────────────────────────────── */

function ExecSummaryModal({ execBlock, blockIndex, onDiscuss, newsCatalog, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-[2px]" onClick={onClose}>
      <div
        className="relative w-full max-w-2xl max-h-[80vh] mx-4 rounded-2xl bg-white shadow-2xl border border-slate-200 overflow-y-auto animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-3 right-3 p-1.5 rounded-lg hover:bg-slate-100 transition text-slate-400 hover:text-slate-600 z-10"
        >
          <X className="w-4 h-4" />
        </button>
        <div className="p-6">
          <ExecSummaryBlock
            content={execBlock.content}
            blockIndex={blockIndex}
            onDiscuss={onDiscuss}
            newsCatalog={newsCatalog}
          />
        </div>
      </div>
    </div>
  )
}

/* ────────────────────────────── Section navigation sidebar ──────────────────────────── */

function SectionNav({ navItems, activeKey, onSelect, collapsed, onToggle, triageResults = [] }) {
  const [triageOpen, setTriageOpen] = useState(false)
  const notable = triageResults.filter(t => t.notable)
  const skipped = triageResults.filter(t => !t.notable)

  return (
    <>
      {/* Collapsed toggle for small screens */}
      <button
        type="button"
        onClick={onToggle}
        className="lg:hidden fixed top-20 left-2 z-30 p-2 rounded-lg bg-slate-100 border border-slate-200 shadow-sm text-slate-500 hover:text-slate-700 hover:bg-slate-200 transition"
      >
        <Menu className="w-4 h-4" />
      </button>

      {/* Overlay backdrop on small screens when open */}
      {!collapsed && (
        <div className="lg:hidden fixed inset-0 z-20 bg-black/20" onClick={onToggle} />
      )}

      <nav
        className={`
          shrink-0 flex flex-col h-full bg-slate-50 border-r border-slate-200/80 overflow-y-auto
          transition-all duration-200 ease-in-out
          ${collapsed
            ? 'w-0 min-w-0 opacity-0 pointer-events-none lg:w-[17%] lg:min-w-[170px] lg:max-w-[220px] lg:opacity-100 lg:pointer-events-auto'
            : 'fixed inset-y-0 left-0 z-20 w-64 lg:relative lg:w-[17%] lg:min-w-[170px] lg:max-w-[220px]'
          }
        `}
      >
        <div className="flex items-center justify-between px-4 pt-5 pb-3 lg:hidden">
          <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Sections</span>
          <button onClick={onToggle} className="p-1 rounded hover:bg-slate-200 text-slate-400">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="hidden lg:block px-4 pt-5 pb-3">
          <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Sections</span>
        </div>
        <ul className="flex-1 px-2 pb-2 space-y-0.5">
          {navItems.map((item) => {
            const isActive = item.key === activeKey
            return (
              <li key={item.key}>
                <button
                  type="button"
                  onClick={() => { onSelect(item.key); if (!collapsed) onToggle?.() }}
                  className={`
                    w-full text-left px-3 py-2.5 rounded-lg text-[12.5px] leading-snug transition-all duration-150
                    ${isActive
                      ? 'bg-slate-200/70 text-slate-800 font-semibold border-l-2 border-slate-600'
                      : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700 border-l-2 border-transparent'
                    }
                  `}
                >
                  {item.label}
                </button>
              </li>
            )
          })}
        </ul>

        {/* Triage summary */}
        {triageResults.length > 0 && (
          <div className="shrink-0 border-t border-slate-200/80 px-3 py-2">
            <button
              type="button"
              onClick={() => setTriageOpen(v => !v)}
              className="inline-flex items-center gap-1.5 text-[10px] font-medium text-slate-400 hover:text-slate-600 transition w-full"
            >
              {triageOpen ? <ChevronDown className="w-2.5 h-2.5" /> : <ChevronRight className="w-2.5 h-2.5" />}
              <BarChart3 className="w-2.5 h-2.5" />
              <span>{notable.length} KPIs · {skipped.length} filtered</span>
            </button>
            {triageOpen && (
              <div className="mt-1.5 space-y-0.5">
                {triageResults.map((t) => (
                  <div key={t.kpi_id} className="flex items-start gap-1.5 py-1">
                    <span className={`text-[9px] mt-0.5 ${t.notable ? 'text-emerald-500' : 'text-slate-300'}`}>
                      {t.notable ? '●' : '○'}
                    </span>
                    <span className={`text-[10px] leading-tight ${t.notable ? 'text-slate-600' : 'text-slate-400'}`}>
                      {t.kpi_name}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </nav>
    </>
  )
}

/* ───────────────────────────── Three-column brief view ──────────────────────────────── */

function ColumnBriefView({
  blocks,
  kpiDataCache,
  fdiBenchmark,
  fdiFlowMode,
  onFdiFlowModeChange,
  onFdiBenchmarkYearChange,
  onDiscuss,
  newsCatalog = [],
  triageResults,
}) {
  const metricsBlock = blocks.find(b => b.type === 'metrics_ribbon')
  const execBlock = blocks.find(b => b.type === 'executive_summary')
  const sectionBlocks = blocks.filter(b => b.type === 'section')
  const outlookBlock = blocks.find(b => b.type === 'outlook')

  const getBlockIndex = (block) => blocks.indexOf(block)

  const navItems = useMemo(() => {
    const items = []
    if (execBlock) items.push({ key: 'exec', label: 'Executive Summary' })
    sectionBlocks.forEach((s) => {
      items.push({ key: `section-${getBlockIndex(s)}`, label: s.title, block: s })
    })
    if (outlookBlock) items.push({ key: 'outlook', label: 'Forward Outlook' })
    return items
  }, [blocks])

  const [activeKey, setActiveKey] = useState(() => {
    const firstSection = navItems.find(n => n.key !== 'exec')
    return firstSection?.key ?? navItems[0]?.key ?? 'exec'
  })
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true)
  const [execModalOpen, setExecModalOpen] = useState(false)
  const prevKeyRef = useRef(activeKey)

  useEffect(() => {
    if (navItems.length && !navItems.find(n => n.key === activeKey)) {
      setActiveKey(navItems[0]?.key ?? 'exec')
    }
  }, [navItems, activeKey])

  const handleNavSelect = useCallback((key) => {
    if (key === 'exec') {
      setExecModalOpen(true)
      return
    }
    prevKeyRef.current = activeKey
    setActiveKey(key)
  }, [activeKey])

  const activeItem = navItems.find(n => n.key === activeKey)
  const activeSection = activeItem?.block ?? null
  const isOutlook = activeKey === 'outlook'
  const isExec = activeKey === 'exec'

  const charts = activeSection?.children?.filter(c => c.type === 'chart_ref') || []
  const narratives = activeSection?.children?.filter(c => c.type === 'narrative') || []
  const activeSectionIdx = activeSection ? getBlockIndex(activeSection) : null

  return (
    <div className="flex flex-col h-full">
      {/* Sticky metrics ribbon */}
      {metricsBlock && (
        <div className="shrink-0 sticky top-0 z-10">
          <MetricsRibbon metrics={metricsBlock.metrics} kpiDataCache={kpiDataCache} />
        </div>
      )}

      {/* Three-column body */}
      <div className="flex flex-1 min-h-0 max-w-[1600px] w-full mx-auto">
        {/* LEFT — section nav */}
        <SectionNav
          navItems={navItems}
          activeKey={activeKey}
          onSelect={handleNavSelect}
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed(v => !v)}
          triageResults={triageResults}
        />

        {/* CENTER — charts */}
        <div className="flex-1 min-w-0 max-w-[900px] overflow-y-auto bg-slate-50/30">
          <div className="p-5 space-y-5" key={activeKey}>
            {activeSection && (
              <div className="opacity-0 animate-[fadeIn_200ms_ease-out_forwards]">
                {charts.length > 0 ? charts.map((child, cIdx) => (
                  <div key={cIdx} className="mb-5">
                    <InlineChartBlock
                      kpiId={child.kpi_id}
                      kpiDataCache={kpiDataCache}
                      fdiBenchmark={fdiBenchmark}
                      fdiFlowMode={fdiFlowMode}
                      onFdiFlowModeChange={onFdiFlowModeChange}
                      onFdiBenchmarkYearChange={onFdiBenchmarkYearChange}
                      exhibitLabel={child.exhibit_label || null}
                      compact
                    />
                  </div>
                )) : (
                  <div className="flex items-center justify-center h-48 text-xs text-slate-300">
                    No chart data for this section
                  </div>
                )}
              </div>
            )}

            {isOutlook && (
              <div className="opacity-0 animate-[fadeIn_200ms_ease-out_forwards]">
                <div className="flex items-center justify-center h-48 text-xs text-slate-300">
                  See outlook insights in the right panel
                </div>
              </div>
            )}

            {isExec && !activeSection && !isOutlook && (
              <div className="flex items-center justify-center h-48 text-xs text-slate-300">
                Select a section from the sidebar
              </div>
            )}
          </div>
        </div>

        {/* RIGHT — insights + docked refine chat */}
        <div className="flex-[0_0_35%] min-w-[280px] max-w-[480px] flex flex-col h-full border-l border-slate-200 bg-white">
          {/* Insights scroll area */}
          <div className="flex-1 overflow-y-auto p-4 lg:p-5 space-y-2" key={`insights-${activeKey}`}>
            {activeSection && narratives.length > 0 && (
              <div className="opacity-0 animate-[fadeIn_200ms_ease-out_forwards]">
                {narratives.map((child, cIdx) => (
                  <NarrativeBlock
                    key={cIdx}
                    variant="insights"
                    content={child.content}
                    blockIndex={cIdx}
                    sectionIndex={activeSectionIdx}
                    sectionTitle={activeSection.title}
                    onDiscuss={onDiscuss}
                    newsCatalog={newsCatalog}
                  />
                ))}
              </div>
            )}

            {isOutlook && outlookBlock && (
              <div className="opacity-0 animate-[fadeIn_200ms_ease-out_forwards]">
                <OutlookBlock
                  content={outlookBlock.content}
                  blockIndex={getBlockIndex(outlookBlock)}
                  onDiscuss={onDiscuss}
                  newsCatalog={newsCatalog}
                />
              </div>
            )}

            {!activeSection && !isOutlook && (
              <div className="flex items-center justify-center h-32 text-xs text-slate-300">
                Select a section to view insights
              </div>
            )}
          </div>

          {/* Docked refine chat */}
          <BriefSidebar docked />
        </div>
      </div>

      {/* Exec summary modal */}
      {execModalOpen && execBlock && (
        <ExecSummaryModal
          execBlock={execBlock}
          blockIndex={getBlockIndex(execBlock)}
          onDiscuss={onDiscuss}
          newsCatalog={newsCatalog}
          onClose={() => setExecModalOpen(false)}
        />
      )}
    </div>
  )
}

export default function CountryBrief() {
  const navigate = useNavigate()
  const downloadMenuRef = useRef(null)
  const triagePopupRef = useRef(null)
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false)
  const [triagePopupOpen, setTriagePopupOpen] = useState(false)
  const [viewMode, setViewMode] = useState('columns') // 'columns' | 'scroll'
  const [focusMode, setFocusMode] = useState(false)
  const {
    countryOptions, countryNames, selectedCountry,
    startYear, endYear, focus, generating, statusMessage, streamingText,
    blocks, kpiDataCache, fdiBenchmark, fdiFlowMode, triageResults, error, briefGenerated, newsArticles,
    setSelectedCountry, setStartYear, setEndYear, setFocus,
    generateBrief, resetBrief, openSidebar, setFdiFlowMode,
    kpiSelectionMode, setKpiSelectionMode, kpiCatalog, selectedKpiIds, toggleKpiId, fetchKpiCatalog,
    generationMode, setGenerationMode,
    chartOrderProfile, setChartOrderProfile,
    debugMode, fetchDebugMode, storeTestReport, loadTestReport,
    refreshFdiBenchmark,
  } = useCountryBriefStore()

  useEffect(() => { fetchKpiCatalog(); fetchDebugMode() }, [fetchKpiCatalog, fetchDebugMode])

  const handleDiscuss = useCallback((blockIndex, title, content) => {
    openSidebar(blockIndex, title, content)
  }, [openSidebar])

  const handleExportMarkdown = useCallback(() => {
    if (!blocks.length) return
    const lines = []
    const country = countryNames[selectedCountry] || selectedCountry
    lines.push(`# ${country} — Macroeconomic Brief`)
    lines.push(`**Period:** ${startYear}–${endYear}`)
    if (focus) lines.push(`**Focus:** ${focus}`)
    lines.push('')

    for (const block of blocks) {
      if (block.type === 'executive_summary') {
        lines.push('## Executive Summary', '', block.content, '')
      } else if (block.type === 'section') {
        lines.push(`## ${block.title}`, '')
        for (const child of block.children || []) {
          if (child.type === 'narrative') lines.push(child.content, '')
        }
      } else if (block.type === 'outlook') {
        lines.push('## Forward Outlook', '', block.content, '')
      }
    }

    const text = lines.join('\n')
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${selectedCountry}_brief_${startYear}-${endYear}.md`
    a.click()
    URL.revokeObjectURL(url)
  }, [blocks, selectedCountry, countryNames, startYear, endYear, focus])

  useEffect(() => {
    function handleClickOutside(event) {
      if (!downloadMenuRef.current?.contains(event.target)) {
        setDownloadMenuOpen(false)
      }
      if (!triagePopupRef.current?.contains(event.target)) {
        setTriagePopupOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const buildReportHtml = useCallback(() => {
    if (!blocks.length) return
    const reportRoot = document.querySelector('[data-country-brief-report]')
    if (!reportRoot) return ''

    const country = countryNames[selectedCountry] || selectedCountry
    const cssText = collectInlineCssText()
    const safeCountry = escapeHtml(country)
    const safePeriod = escapeHtml(`${startYear}\u2013${endYear}`)
    const safeMode = escapeHtml(generationMode === 'deep' ? 'Deep mode' : 'Light mode')
    const safeFocus = focus ? escapeHtml(focus) : ''
    const focusHtml = safeFocus
      ? `<p class="text-xs text-slate-500 mt-1"><span class="font-semibold text-slate-600">Focus:</span> ${safeFocus}</p>`
      : ''

    const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${safeCountry} - Country Brief</title>
  <style>${cssText}</style>
  <style>
    :root {
      --color-mck-navy: #051C2C;
      --color-mck-blue: #2251FF;
      --color-mck-deep: #24477F;
      --color-mck-sky: #4B8BBE;
      --color-mck-light: #7CA5C2;
      --color-mck-pale: #A8BFD0;
      --color-mck-body: #333333;
    }
    body { margin: 0; background: #f8fafc; color: #0f172a; }
    .download-shell { max-width: 1280px; margin: 0 auto; padding: 24px 20px 40px; }
    .download-header { max-width: 56rem; margin: 0 auto 16px; }
    .recharts-wrapper, .recharts-wrapper svg { overflow: visible !important; }
    @media print {
      body { background: #fff; }
      .download-shell { padding: 0; }
      .recharts-wrapper, .recharts-wrapper svg { overflow: visible !important; }
    }
  </style>
</head>
<body>
  <main class="download-shell">
    <header class="download-header">
      <h1 class="text-2xl font-bold text-slate-800">${safeCountry}</h1>
      <p class="text-xs text-slate-500">${safePeriod} &middot; ${safeMode}</p>
      ${focusHtml}
    </header>
    ${reportRoot.outerHTML}
  </main>
</body>
</html>`
    return html
  }, [blocks, countryNames, selectedCountry, startYear, endYear, generationMode, focus])

  const handleDownloadHtml = useCallback(() => {
    const html = buildReportHtml()
    if (!html) return
    const period = `${startYear}-${endYear}`

    const blob = new Blob([html], { type: 'text/html;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${selectedCountry}_brief_${period}.html`
    a.click()
    URL.revokeObjectURL(url)
    setDownloadMenuOpen(false)
  }, [buildReportHtml, selectedCountry, startYear, endYear])

  const handleDownloadPdf = useCallback(() => {
    const html = buildReportHtml()
    if (!html) return

    const printWindow = window.open('', '_blank')
    if (!printWindow) return
    printWindow.document.open()
    printWindow.document.write(html)
    printWindow.document.close()
    const triggerPrint = () => {
      printWindow.focus()
      printWindow.print()
    }
    printWindow.onload = () => setTimeout(triggerPrint, 150)
    setDownloadMenuOpen(false)
  }, [buildReportHtml])

  // --- Landing page: country selector + focus ---
  if (!briefGenerated && !generating) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-10">
          <div className="text-center mb-10">
            <h1 className="text-2xl font-bold text-slate-800 mb-2">Country Brief</h1>
            <p className="text-sm text-slate-500">
              Select a country to generate an AI-driven macroeconomic brief with automated insights.
            </p>
          </div>

          <CountrySelector
            countryOptions={countryOptions}
            countryNames={countryNames}
            selectedCountry={selectedCountry}
            onSelect={setSelectedCountry}
          />

          {/* KPI selection mode */}
          <div className="mt-8 max-w-lg mx-auto">
            <h3 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-3 text-center">KPI Selection</h3>
            <div className="flex justify-center mb-4">
              <div className="inline-flex rounded-xl overflow-hidden border border-slate-200">
                <button type="button"
                  onClick={() => setKpiSelectionMode('auto')}
                  className={`px-5 py-2.5 text-xs font-semibold transition-all ${
                    kpiSelectionMode === 'auto'
                      ? 'bg-slate-800 text-white'
                      : 'bg-white text-slate-500 hover:bg-slate-50'
                  }`}
                >Automatic</button>
                <button type="button"
                  onClick={() => setKpiSelectionMode('manual')}
                  className={`px-5 py-2.5 text-xs font-semibold transition-all ${
                    kpiSelectionMode === 'manual'
                      ? 'bg-slate-800 text-white'
                      : 'bg-white text-slate-500 hover:bg-slate-50'
                  }`}
                >Manual</button>
              </div>
            </div>

            <div className={`rounded-xl border border-slate-200 bg-white p-4 transition-opacity ${
              kpiSelectionMode === 'auto' ? 'opacity-40 pointer-events-none' : ''
            }`}>
              {kpiCatalog.length === 0 ? (
                <p className="text-xs text-slate-400 text-center py-2">Loading KPIs…</p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {kpiCatalog.filter(k => k.available !== false).map(kpi => {
                    const checked = selectedKpiIds.includes(kpi.id)
                    return (
                      <label key={kpi.id}
                        className={`flex items-start gap-2.5 px-3 py-2.5 rounded-lg cursor-pointer transition-colors ${
                          checked ? 'bg-blue-50 border border-blue-200' : 'border border-transparent hover:bg-slate-50'
                        }`}
                      >
                        <input type="checkbox" checked={checked}
                          onChange={() => toggleKpiId(kpi.id)}
                          className="mt-0.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                        />
                        <div className="min-w-0">
                          <span className="text-sm text-slate-700 font-medium leading-snug block">{kpi.name}</span>
                          {kpi.notes && <span className="text-[10px] text-slate-400 leading-tight block mt-0.5">{kpi.notes}</span>}
                        </div>
                      </label>
                    )
                  })}
                </div>
              )}
            </div>
            {kpiSelectionMode === 'auto' && (
              <p className="text-[10px] text-slate-400 text-center mt-2">
                KPIs will be selected automatically based on country and focus.
              </p>
            )}
            {kpiSelectionMode === 'manual' && selectedKpiIds.length > 0 && (
              <p className="text-[10px] text-slate-400 text-center mt-2">
                {selectedKpiIds.length} KPI{selectedKpiIds.length !== 1 ? 's' : ''} selected
              </p>
            )}
          </div>

          <div className="mt-8 max-w-md mx-auto">
            <h3 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-3 text-center">Time Range</h3>
            <div className="flex items-center gap-3 justify-center">
              <div>
                <label className="text-[10px] text-slate-400 mb-0.5 block">From</label>
                <input type="number" min={1990} max={endYear} value={startYear}
                  onChange={e => { const v = parseInt(e.target.value, 10); if (!isNaN(v)) setStartYear(v) }}
                  className="w-24 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none tabular-nums" />
              </div>
              <span className="text-slate-300 mt-4 text-lg">—</span>
              <div>
                <label className="text-[10px] text-slate-400 mb-0.5 block">To</label>
                <input type="number" min={startYear} max={new Date().getFullYear() + 5} value={endYear}
                  onChange={e => { const v = parseInt(e.target.value, 10); if (!isNaN(v)) setEndYear(v) }}
                  className="w-24 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none tabular-nums" />
              </div>
            </div>
          </div>

          <div className="mt-8 max-w-md mx-auto">
            <h3 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-3 text-center">Analysis Mode</h3>
            <div className="flex justify-center">
              <div className="inline-flex rounded-xl overflow-hidden border border-slate-200">
                <button
                  type="button"
                  onClick={() => setGenerationMode('light')}
                  className={`px-5 py-2.5 text-xs font-semibold transition-all ${
                    generationMode === 'light'
                      ? 'bg-slate-800 text-white'
                      : 'bg-white text-slate-500 hover:bg-slate-50'
                  }`}
                >
                  Light
                </button>
                <button
                  type="button"
                  onClick={() => setGenerationMode('deep')}
                  className={`px-5 py-2.5 text-xs font-semibold transition-all ${
                    generationMode === 'deep'
                      ? 'bg-slate-800 text-white'
                      : 'bg-white text-slate-500 hover:bg-slate-50'
                  }`}
                >
                  Deep
                </button>
              </div>
            </div>
            <p className="text-[10px] text-slate-400 text-center mt-2">
              Light is default and lower-cost; deep adds richer external evidence.
            </p>
          </div>

          <div className="mt-8 max-w-md mx-auto">
            <h3 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-3 text-center">Chart Order</h3>
            <div className="flex justify-center">
              <div className="inline-flex rounded-xl overflow-hidden border border-slate-200">
                <button
                  type="button"
                  onClick={() => setChartOrderProfile('default')}
                  className={`px-5 py-2.5 text-xs font-semibold transition-all ${
                    chartOrderProfile === 'default'
                      ? 'bg-slate-800 text-white'
                      : 'bg-white text-slate-500 hover:bg-slate-50'
                  }`}
                >
                  New Flow
                </button>
                <button
                  type="button"
                  onClick={() => setChartOrderProfile('legacy')}
                  className={`px-5 py-2.5 text-xs font-semibold transition-all ${
                    chartOrderProfile === 'legacy'
                      ? 'bg-slate-800 text-white'
                      : 'bg-white text-slate-500 hover:bg-slate-50'
                  }`}
                >
                  Standard
                </button>
              </div>
            </div>
            <p className="text-[10px] text-slate-400 text-center mt-2">
              {chartOrderProfile === 'default'
                ? 'Oil/Non-oil → Growth → Sector → Inflation → Consumption → Trade → FDI → Fiscal → Debt → Unemployment → Population'
                : 'Growth → Oil/Non-oil → Sector → FDI → Debt → Inflation → Unemployment → Consumption → Population'}
            </p>
          </div>

          {/* Focus input */}
          <div className="mt-8 max-w-lg mx-auto">
            <div className="flex items-center gap-2 mb-2">
              <Target className="w-3.5 h-3.5 text-slate-400" />
              <h3 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                Focus (optional)
              </h3>
            </div>
            <textarea
              value={focus}
              onChange={e => setFocus(e.target.value)}
              rows={2}
              placeholder="E.g., 'Focus on non-oil diversification and Vision 2030 progress' or 'Emphasize investment climate and FDI trends'"
              className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-700 resize-none outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 placeholder:text-slate-300 leading-relaxed"
            />
          </div>

          {error && (
            <div className="mt-6 rounded-lg bg-red-50 border border-red-200 text-red-700 px-4 py-3 text-xs max-w-md mx-auto">{error}</div>
          )}

          <div className="mt-8 flex flex-col items-center gap-3">
            <button
              onClick={generateBrief}
              disabled={!selectedCountry || generating}
              className="px-8 py-3.5 text-sm font-bold text-white rounded-xl transition-all shadow-lg disabled:opacity-50
                bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-700
                hover:from-indigo-700 hover:via-purple-700 hover:to-indigo-800
                shadow-indigo-600/30 hover:shadow-indigo-700/40
                active:scale-[0.98] inline-flex items-center gap-2.5"
            >
              <Sparkles className="w-4 h-4" />
              Generate Brief{selectedCountry ? ` — ${countryNames[selectedCountry] || selectedCountry}` : ''}
            </button>
            {debugMode && (
              <button
                onClick={loadTestReport}
                className="inline-flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-xl hover:bg-amber-100 transition"
              >
                <Upload className="w-3.5 h-3.5" />Load test report
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  // --- Streaming / generating state ---
  if (generating && !briefGenerated) {
    return (
      <div className="h-full overflow-y-auto">
        <StreamingProgress statusMessage={statusMessage} streamingText={streamingText} />
      </div>
    )
  }

  // --- Brief view ---
  const isColumnView = viewMode === 'columns'

  return (
    <div className="flex flex-col h-full">
      {/* Brief header — hidden in focus mode */}
      {!focusMode && (
        <div className="shrink-0 px-6 py-2 border-b border-slate-100 bg-white">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                type="button"
                title="Home"
                onClick={() => navigate('/')}
                className="p-1.5 rounded-lg hover:bg-slate-100 transition text-slate-500 hover:text-slate-700"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
              <div>
                <h1 className="text-base font-bold text-slate-800">
                  {countryNames[selectedCountry] || selectedCountry}
                </h1>
                <div className="flex items-center gap-2">
                  <p className="text-xs text-slate-400">
                    {startYear}–{endYear}
                    {` · ${generationMode === 'deep' ? 'Deep' : 'Light'} mode`}
                    {focus ? ` · ${focus.slice(0, 60)}${focus.length > 60 ? '...' : ''}` : ''}
                  </p>
                  {triageResults.length > 0 && (
                    <div className="relative" ref={triagePopupRef}>
                      <button
                        type="button"
                        onClick={() => setTriagePopupOpen(v => !v)}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium text-slate-500 bg-slate-100 hover:bg-slate-200 transition"
                      >
                        <BarChart3 className="w-2.5 h-2.5" />
                        {triageResults.filter(t => t.notable).length} KPIs selected · {triageResults.filter(t => !t.notable).length} filtered
                        <ChevronDown className={`w-2.5 h-2.5 transition-transform ${triagePopupOpen ? 'rotate-180' : ''}`} />
                      </button>
                      {triagePopupOpen && (
                        <div className="absolute left-0 top-full mt-1.5 w-72 rounded-xl border border-slate-200 bg-white shadow-xl py-1 z-[60]">
                          <div className="divide-y divide-slate-50">
                            {triageResults.map((t) => (
                              <div key={t.kpi_id} className="flex items-center gap-2.5 px-3 py-2">
                                {t.notable ? (
                                  <CheckCircle2 className="w-3 h-3 text-emerald-500 shrink-0" />
                                ) : (
                                  <XCircle className="w-3 h-3 text-slate-300 shrink-0" />
                                )}
                                <span className={`text-[11px] ${t.notable ? 'text-slate-700 font-medium' : 'text-slate-400'}`}>
                                  {t.kpi_name}
                                </span>
                                <span className="ml-auto text-[9px] font-mono text-slate-400">{t.score}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap justify-end">
              {/* View mode toggle */}
              <div className="inline-flex rounded-lg overflow-hidden border border-slate-200">
                <button
                  type="button"
                  onClick={() => setViewMode('columns')}
                  title="Column view"
                  className={`p-2 transition-all ${isColumnView ? 'bg-slate-800 text-white' : 'bg-white text-slate-400 hover:bg-slate-50 hover:text-slate-600'}`}
                >
                  <Columns3 className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode('scroll')}
                  title="Free-scroll view"
                  className={`p-2 transition-all ${!isColumnView ? 'bg-slate-800 text-white' : 'bg-white text-slate-400 hover:bg-slate-50 hover:text-slate-600'}`}
                >
                  <ScrollText className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* Focus mode toggle */}
              <button
                type="button"
                onClick={() => setFocusMode(true)}
                title="Focus mode"
                className="p-2 rounded-lg border border-slate-200 bg-white text-slate-400 hover:bg-slate-50 hover:text-slate-600 transition"
              >
                <Maximize2 className="w-3.5 h-3.5" />
              </button>

              {debugMode && (
                <button
                  type="button"
                  onClick={storeTestReport}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-xl hover:bg-amber-100 transition"
                >
                  <DatabaseBackup className="w-3.5 h-3.5" />Store test report
                </button>
              )}
              <button
                type="button"
                onClick={resetBrief}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 hover:text-slate-700 transition"
              >
                Start over
              </button>
              <div className="relative" ref={downloadMenuRef}>
                <button
                  type="button"
                  onClick={() => setDownloadMenuOpen(v => !v)}
                  disabled={!blocks.length}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition disabled:opacity-40"
                >
                  <Download className="w-3.5 h-3.5" />Download
                  <ChevronDown className={`w-3.5 h-3.5 transition-transform ${downloadMenuOpen ? 'rotate-180' : ''}`} />
                </button>
                {downloadMenuOpen && (
                  <div className="absolute right-0 mt-1.5 w-36 rounded-xl border border-slate-200 bg-white shadow-lg py-1 z-[60]">
                    <button
                      type="button"
                      onClick={handleDownloadHtml}
                      className="w-full px-3 py-2 text-left text-xs font-medium text-slate-600 hover:bg-slate-50"
                    >
                      Download HTML
                    </button>
                    <button
                      type="button"
                      onClick={handleDownloadPdf}
                      className="w-full px-3 py-2 text-left text-xs font-medium text-slate-600 hover:bg-slate-50"
                    >
                      Download PDF
                    </button>
                  </div>
                )}
              </div>
              <button onClick={handleExportMarkdown}
                disabled={!blocks.length}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition disabled:opacity-40"
              >
                <FileText className="w-3.5 h-3.5" />Markdown
              </button>
              <button onClick={generateBrief}
                disabled={generating}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white rounded-xl transition-all
                  bg-gradient-to-r from-indigo-600 to-purple-600
                  hover:from-indigo-700 hover:to-purple-700
                  shadow-sm disabled:opacity-50 active:scale-[0.98]"
              >
                <RotateCcw className="w-3.5 h-3.5" />Regenerate
              </button>
            </div>
          </div>

          {error && (
            <div className="mt-2 rounded-lg bg-red-50 border border-red-200 text-red-700 px-4 py-3 text-xs">{error}</div>
          )}
        </div>
      )}

      {/* Floating exit-focus button */}
      {focusMode && (
        <button
          type="button"
          onClick={() => setFocusMode(false)}
          title="Exit focus mode"
          className="fixed top-14 right-4 z-50 p-2 rounded-lg bg-white/80 border border-slate-200 text-slate-400 hover:bg-white hover:text-slate-600 shadow-sm backdrop-blur-sm transition"
        >
          <Minimize2 className="w-3.5 h-3.5" />
        </button>
      )}

      {/* View body */}
      {isColumnView ? (
        <>
          <div className="flex-1 min-h-0">
            <ColumnBriefView
              blocks={blocks}
              kpiDataCache={kpiDataCache}
              fdiBenchmark={fdiBenchmark}
              fdiFlowMode={fdiFlowMode}
              onFdiFlowModeChange={setFdiFlowMode}
              onFdiBenchmarkYearChange={refreshFdiBenchmark}
              onDiscuss={handleDiscuss}
              newsCatalog={newsArticles}
              triageResults={triageResults}
            />
          </div>
          {/* Hidden full document for HTML/PDF export */}
          <div className="absolute -left-[9999px] w-[1280px]" aria-hidden="true" data-country-brief-report>
            <FreeScrollDocument
              blocks={blocks}
              kpiDataCache={kpiDataCache}
              fdiBenchmark={fdiBenchmark}
              fdiFlowMode={fdiFlowMode}
              onFdiFlowModeChange={setFdiFlowMode}
              onFdiBenchmarkYearChange={refreshFdiBenchmark}
              onDiscuss={handleDiscuss}
              newsCatalog={newsArticles}
            />
          </div>
        </>
      ) : (
        <div className="flex flex-1 min-h-0">
          <div className="flex-1 overflow-y-auto">
            <div data-country-brief-report>
              <FreeScrollDocument
                blocks={blocks}
                kpiDataCache={kpiDataCache}
                fdiBenchmark={fdiBenchmark}
                fdiFlowMode={fdiFlowMode}
                onFdiFlowModeChange={setFdiFlowMode}
                onFdiBenchmarkYearChange={refreshFdiBenchmark}
                onDiscuss={handleDiscuss}
                newsCatalog={newsArticles}
              />
            </div>
            <div className="h-16" />
          </div>
          <BriefSidebar />
        </div>
      )}
    </div>
  )
}
