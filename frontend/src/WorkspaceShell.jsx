import { useState, useEffect, useRef, useCallback } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Plus, ChevronDown, Globe, Flag, Trash2,
} from 'lucide-react'
import useWorkspaceStore from './stores/workspaceStore'
import useDataStore from './stores/dataStore'
import useCountryBriefStore from './stores/countryBriefStore'

const PRIMARY_NAV = [
  { to: '/country-brief', icon: Flag, label: 'Country Brief' },
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
]

export default function WorkspaceShell() {
  const {
    workspaces, activeWorkspace, loading,
    fetchWorkspaces, createWorkspace, setActiveWorkspace, updateWorkspace, deleteWorkspace,
  } = useWorkspaceStore()
  const hydrateFromWorkspace = useDataStore(s => s.hydrateFromWorkspace)
  const selectedCountries = useDataStore(s => s.selectedCountries)
  const selectedKpis = useDataStore(s => s.selectedKpis)

  const hydrateBriefFromWorkspace = useCountryBriefStore(s => s.hydrateFromWorkspace)
  const briefSelectedCountry = useCountryBriefStore(s => s.selectedCountry)
  const briefStartYear = useCountryBriefStore(s => s.startYear)
  const briefEndYear = useCountryBriefStore(s => s.endYear)
  const briefFocus = useCountryBriefStore(s => s.focus)

  const [showWorkspaceMenu, setShowWorkspaceMenu] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [newWsName, setNewWsName] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)

  /** Wait for country-brief persist rehydration before merging workspace — avoids wiping a cached brief. */
  const [countryBriefPersistReady, setCountryBriefPersistReady] = useState(false)
  const lastBriefHydrateWorkspaceId = useRef(null)

  useEffect(() => { fetchWorkspaces() }, [fetchWorkspaces])

  useEffect(() => {
    return useCountryBriefStore.persist.onFinishHydration(() => {
      setCountryBriefPersistReady(true)
    })
  }, [])

  useEffect(() => {
    if (!countryBriefPersistReady) return
    if (!activeWorkspace?.id) {
      lastBriefHydrateWorkspaceId.current = null
      return
    }
    const id = activeWorkspace.id
    if (lastBriefHydrateWorkspaceId.current === id) return
    lastBriefHydrateWorkspaceId.current = id
    hydrateFromWorkspace(activeWorkspace)
    hydrateBriefFromWorkspace(activeWorkspace.country_brief, id)
  }, [activeWorkspace, countryBriefPersistReady, hydrateFromWorkspace, hydrateBriefFromWorkspace])

  const syncTimerRef = useRef(null)
  useEffect(() => {
    if (!activeWorkspace) return
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current)

    syncTimerRef.current = setTimeout(() => {
      const countriesChanged =
        JSON.stringify([...selectedCountries].sort()) !==
        JSON.stringify([...(activeWorkspace.countries || [])].sort())
      const kpisChanged =
        JSON.stringify([...selectedKpis].sort()) !==
        JSON.stringify([...(activeWorkspace.kpi_ids || [])].sort())

      if (countriesChanged || kpisChanged) {
        updateWorkspace(activeWorkspace.id, {
          countries: selectedCountries,
          kpi_ids: selectedKpis,
        })
      }
    }, 600)

    return () => { if (syncTimerRef.current) clearTimeout(syncTimerRef.current) }
  }, [selectedCountries, selectedKpis, activeWorkspace, updateWorkspace])

  const briefSyncRef = useRef(null)
  useEffect(() => {
    if (!activeWorkspace) return
    if (briefSyncRef.current) clearTimeout(briefSyncRef.current)

    briefSyncRef.current = setTimeout(() => {
      const currentBrief = activeWorkspace.country_brief || {}
      const changed =
        (briefSelectedCountry || null) !== (currentBrief.country || null) ||
        briefStartYear !== (currentBrief.startYear || 2015) ||
        briefEndYear !== (currentBrief.endYear || new Date().getFullYear())

      if (changed && briefSelectedCountry) {
        updateWorkspace(activeWorkspace.id, {
          country_brief: {
            country: briefSelectedCountry,
            startYear: briefStartYear,
            endYear: briefEndYear,
            focus: briefFocus || '',
          },
        })
      }
    }, 600)

    return () => { if (briefSyncRef.current) clearTimeout(briefSyncRef.current) }
  }, [briefSelectedCountry, briefStartYear, briefEndYear, briefFocus, activeWorkspace, updateWorkspace])

  const handleCreateWorkspace = async () => {
    if (!newWsName.trim()) return
    const ws = await createWorkspace({
      name: newWsName,
      description: '',
      countries: selectedCountries,
      kpi_ids: selectedKpis,
    })
    setNewWsName('')
    setShowCreate(false)
  }

  const handleSelectWorkspace = useCallback((ws) => {
    setActiveWorkspace(ws)
    setShowWorkspaceMenu(false)
    setConfirmDeleteId(null)
  }, [setActiveWorkspace])

  const handleDeleteWorkspace = useCallback(async (id) => {
    await deleteWorkspace(id)
    setConfirmDeleteId(null)
  }, [deleteWorkspace])

  const navigate = useNavigate()

  return (
    <div className="flex h-screen bg-slate-50 text-sm">
      <div className="flex flex-col w-full h-full">
        <header className="shrink-0 bg-mck-navy px-4 py-0 flex items-center justify-between h-12">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/')}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              <Globe className="w-5 h-5 text-mck-blue" />
              <h1 className="text-sm font-bold text-white tracking-tight">Macro Brief</h1>
            </button>

            <nav className="flex items-center gap-0.5 ml-4">
              {PRIMARY_NAV.map(({ to, icon: Icon, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) =>
                    `flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-[12px] font-semibold transition
                    ${isActive
                      ? 'bg-mck-blue text-white shadow-sm'
                      : 'text-white/70 hover:text-white hover:bg-white/10'}`
                  }
                >
                  <Icon className="w-3.5 h-3.5" />
                  {label}
                </NavLink>
              ))}
            </nav>
          </div>

          <div className="relative">
            <button
              onClick={() => setShowWorkspaceMenu(!showWorkspaceMenu)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-white/20 hover:bg-white/10 transition text-xs"
            >
              <span className="font-medium text-white/90 max-w-[160px] truncate">
                {activeWorkspace?.name || 'No workspace'}
              </span>
              <ChevronDown className="w-3 h-3 text-white/50" />
            </button>

            {showWorkspaceMenu && (
              <div className="absolute right-0 top-full mt-1 w-64 bg-white rounded-xl shadow-lg border border-slate-200 py-1 z-50">
                <div className="px-3 py-2 border-b border-slate-100">
                  <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">Workspaces</p>
                </div>

                <div className="max-h-48 overflow-y-auto">
                  {workspaces.map(ws => (
                    <div key={ws.id}
                      className={`group flex items-center justify-between px-3 py-2 hover:bg-slate-50 transition
                        ${activeWorkspace?.id === ws.id ? 'bg-mck-blue/5' : ''}`}>
                      {confirmDeleteId === ws.id ? (
                        <div className="flex items-center gap-2 w-full">
                          <span className="text-xs text-red-600 flex-1">Delete?</span>
                          <button onClick={() => handleDeleteWorkspace(ws.id)}
                            className="px-2 py-0.5 text-[10px] font-medium bg-red-600 text-white rounded hover:bg-red-700 transition">
                            Yes
                          </button>
                          <button onClick={() => setConfirmDeleteId(null)}
                            className="px-2 py-0.5 text-[10px] font-medium bg-slate-200 text-slate-600 rounded hover:bg-slate-300 transition">
                            No
                          </button>
                        </div>
                      ) : (
                        <>
                          <button onClick={() => handleSelectWorkspace(ws)} className="flex-1 text-left min-w-0">
                            <p className="text-xs font-medium text-slate-700 truncate">{ws.name}</p>
                            <p className="text-[10px] text-slate-400">{ws.countries?.length || 0} countries · {ws.kpi_ids?.length || 0} KPIs</p>
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(ws.id) }}
                            className="p-1 rounded text-slate-300 opacity-0 group-hover:opacity-100 hover:text-red-500 hover:bg-red-50 transition-all"
                            title="Delete workspace">
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  ))}
                </div>

                <div className="border-t border-slate-100 px-3 py-2">
                  {showCreate ? (
                    <div className="flex gap-1.5">
                      <input value={newWsName} onChange={e => setNewWsName(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleCreateWorkspace()}
                        placeholder="Workspace name…" autoFocus
                        className="flex-1 rounded-md border border-slate-200 px-2 py-1 text-xs outline-none focus:border-mck-deep" />
                      <button onClick={handleCreateWorkspace}
                        className="px-2.5 py-1 bg-mck-navy text-white text-xs rounded-md hover:bg-mck-deep transition">
                        Create
                      </button>
                    </div>
                  ) : (
                    <button onClick={() => setShowCreate(true)}
                      className="w-full flex items-center gap-2 px-2 py-1.5 text-xs text-mck-deep hover:bg-mck-blue/5 rounded-md transition">
                      <Plus className="w-3.5 h-3.5" /> New Workspace
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </header>

        <div className="flex-1 overflow-hidden">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
