import { useState, useEffect, useCallback, useMemo } from 'react'
import { Newspaper, Search, Filter, Clock, TrendingUp, ThumbsUp, ThumbsDown, Minus, RefreshCw } from 'lucide-react'
import useWorkspaceStore from '../../stores/workspaceStore'
import useDataStore from '../../stores/dataStore'

export default function NewsLab() {
  const workspace = useWorkspaceStore(s => s.activeWorkspace)
  const { selectedCountries, results } = useDataStore()
  const [articles, setArticles] = useState([])
  const [loading, setLoading] = useState(false)
  const [infoMessage, setInfoMessage] = useState('')
  const [error, setError] = useState('')
  const [selectedArticle, setSelectedArticle] = useState(null)
  const [filterCountry, setFilterCountry] = useState('all')
  const [viewMode, setViewMode] = useState('feed')

  const loadArticles = useCallback(async () => {
    if (!results.length) {
      setArticles([])
      setInfoMessage('')
      setError('')
      return
    }
    setLoading(true)
    setError('')
    setInfoMessage('')
    try {
      const resp = await fetch('/api/news/lab', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          countries: selectedCountries,
          kpi_result: results[0],
        }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${resp.status}`)
      }
      setArticles(data.articles || [])
      if (data.message) setInfoMessage(data.message)
    } catch (e) {
      setError(e.message || 'Could not load news.')
      setArticles([])
    } finally {
      setLoading(false)
    }
  }, [results, selectedCountries])

  useEffect(() => {
    if (!workspace || !results.length) {
      setArticles([])
      setInfoMessage('')
      setError('')
      return
    }
    loadArticles()
  }, [workspace?.id, loadArticles])

  const visibleArticles = useMemo(() => {
    if (filterCountry === 'all') return articles
    return articles.filter(a => a.country_iso3 === filterCountry || a.country_iso3 == null)
  }, [articles, filterCountry])

  const filterHidesAll = articles.length > 0 && visibleArticles.length === 0 && filterCountry !== 'all'

  if (!workspace) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <p>Select a workspace to explore news context.</p>
      </div>
    )
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-slate-200 px-6 py-4 z-10">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Newspaper className="w-5 h-5 text-slate-600" />
              <h2 className="text-lg font-bold text-slate-800">News Lab</h2>
            </div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => loadArticles()} disabled={loading || !results.length}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-slate-100 text-slate-700 hover:bg-slate-200 disabled:opacity-40 transition">
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                Refresh
              </button>
              <button type="button" onClick={() => setViewMode('feed')}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${viewMode === 'feed' ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600'}`}>
                Feed
              </button>
              <button type="button" onClick={() => setViewMode('timeline')}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${viewMode === 'timeline' ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600'}`}>
                Timeline
              </button>
            </div>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-3 mt-3">
            <div className="flex items-center gap-1.5 bg-slate-50 rounded-lg px-3 py-2 flex-1">
              <Search className="w-4 h-4 text-slate-400" />
              <input placeholder="Search articles…" className="bg-transparent text-sm outline-none flex-1 text-slate-700 placeholder:text-slate-400" />
            </div>
            <select value={filterCountry} onChange={e => setFilterCountry(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700 outline-none">
              <option value="all">All Countries</option>
              {selectedCountries.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
        </div>

        {/* Content */}
        <div className="p-6">
          {error && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              {error}
            </div>
          )}
          {infoMessage && !error && (
            <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
              {infoMessage}
            </div>
          )}
          {loading && (
            <div className="flex items-center gap-2 text-sm text-slate-500 mb-4">
              <span className="inline-block h-4 w-4 rounded-full border-2 border-slate-300 border-t-transparent animate-spin" />
              Loading articles…
            </div>
          )}
          {!loading && visibleArticles.length === 0 ? (
            <div className="text-center py-16">
              <Newspaper className="w-12 h-12 text-slate-200 mx-auto mb-4" />
              <h3 className="text-sm font-medium text-slate-600 mb-2">
                {results.length === 0 ? 'Fetch KPI data first'
                  : filterHidesAll ? 'No articles for this country filter' : 'No articles to show yet'}
              </h3>
              <p className="text-xs text-slate-400 max-w-md mx-auto">
                {results.length === 0
                  ? 'Open the Dashboard, select countries and KPIs, and run a data fetch. News Lab uses the first KPI in your results to search and rank articles from Newscatcher.'
                  : filterHidesAll
                    ? 'Switch the country dropdown to “All Countries” or choose a country that matches the tagged geography for these articles.'
                    : 'Try Refresh, pick another KPI on the Dashboard (first KPI in your results is used), or check that NEWSCATCHER_API_KEY is set in your environment.'}
              </p>
              <div className="mt-6 grid grid-cols-3 gap-4 max-w-lg mx-auto">
                <div className="rounded-lg border border-slate-100 p-3 text-center">
                  <Filter className="w-5 h-5 text-blue-400 mx-auto mb-1" />
                  <p className="text-[10px] text-slate-500">Filter by country, KPI, sentiment</p>
                </div>
                <div className="rounded-lg border border-slate-100 p-3 text-center">
                  <Clock className="w-5 h-5 text-amber-400 mx-auto mb-1" />
                  <p className="text-[10px] text-slate-500">Timeline view with KPI overlay</p>
                </div>
                <div className="rounded-lg border border-slate-100 p-3 text-center">
                  <TrendingUp className="w-5 h-5 text-green-400 mx-auto mb-1" />
                  <p className="text-[10px] text-slate-500">Link articles to graph nodes</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {visibleArticles.map((article, i) => (
                <ArticleCard key={`${article.title}-${article.date}-${i}`} article={article} onClick={() => setSelectedArticle(article)} />
              ))}
            </div>
          )}
        </div>
      </div>

      {selectedArticle && (
        <aside className="w-96 border-l border-slate-200 bg-white overflow-y-auto p-6">
          <h3 className="text-sm font-semibold text-slate-800 mb-3">{selectedArticle.title}</h3>
          <div className="text-xs text-slate-600 leading-relaxed">{selectedArticle.snippet || selectedArticle.content}</div>
          <button onClick={() => setSelectedArticle(null)} className="mt-4 text-xs text-slate-400 hover:text-slate-600">Close</button>
        </aside>
      )}
    </div>
  )
}

function ArticleCard({ article, onClick }) {
  const sentiment = article.sentiment
  const SentIcon = sentiment > 0.1 ? ThumbsUp : sentiment < -0.1 ? ThumbsDown : Minus
  const sentColor = sentiment > 0.1 ? 'text-green-500' : sentiment < -0.1 ? 'text-red-500' : 'text-slate-400'

  return (
    <div onClick={onClick}
      className="rounded-xl border border-slate-200 bg-white p-4 hover:border-blue-300 hover:shadow-sm transition cursor-pointer">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-medium text-slate-800 line-clamp-2">{article.title}</h4>
          <div className="flex items-center gap-2 mt-1.5">
            <span className="text-[10px] text-slate-400">{article.source}</span>
            <span className="text-[10px] text-slate-300">·</span>
            <span className="text-[10px] text-slate-400">{article.date}</span>
            {article.score && (
              <>
                <span className="text-[10px] text-slate-300">·</span>
                <span className="text-[10px] text-blue-500 font-medium">Score: {article.score}</span>
              </>
            )}
          </div>
        </div>
        <SentIcon className={`w-4 h-4 shrink-0 ${sentColor}`} />
      </div>
      <p className="text-xs text-slate-500 mt-2 line-clamp-2">{article.snippet}</p>
    </div>
  )
}
