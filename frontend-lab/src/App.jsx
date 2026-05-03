import { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'

const COUNTRY_OPTIONS = [
  'SAU', 'ARE', 'QAT', 'KWT', 'BHR', 'OMN',
  'USA', 'GBR', 'DEU', 'FRA', 'JPN', 'CHN', 'IND', 'BRA',
]

const STAGE_ORDER = [
  { key: 'data_fetch', label: 'Data Fetch', blurb: 'Load KPI time-series and validate scope.' },
  { key: 'signal_extractor', label: 'Signal Extractor', blurb: 'Detect deterministic patterns and triage relevance.' },
  { key: 'hypotheses_generator', label: 'Hypotheses Generator', blurb: 'Build broad causal explanations for the KPI shifts.' },
  { key: 'news_researcher', label: 'News Researcher', blurb: 'Corroborate hypotheses against external evidence.' },
  { key: 'insights_generator_first_pass', label: 'Insights First Pass', blurb: 'Create initial insights and forward view.' },
  { key: 'evaluator', label: 'Evaluator', blurb: 'Critique correctness, causality, and overreach.' },
  { key: 'insights_generator', label: 'Insights Revision Pass', blurb: 'Apply evaluator feedback once and finalize.' },
  { key: 'brief_writer', label: 'Brief Writer', blurb: 'Produce the final polished macro brief.' },
]

const RUN_HISTORY_KEY = 'macrobrief-lab-run-history-v1'

function currency(value) {
  const n = Number(value || 0)
  return `$${n.toFixed(6)}`
}

function stageState(stageContent, stageKey) {
  return Object.prototype.hasOwnProperty.call(stageContent, stageKey) ? 'done' : 'pending'
}

function summarizePrediction(pred) {
  if (typeof pred === 'string') return pred
  if (!pred || typeof pred !== 'object') return 'Prediction generated.'
  return pred.headline || pred.title || pred.statement || pred.analysis || 'Prediction generated.'
}

function StageDataFetch({ data }) {
  return (
    <div className="stageBody">
      <p><strong>{data.kpi_name}</strong> ({data.kpi_id}) fetched for <strong>{data.country}</strong>.</p>
      <div className="chipRow">
        <span className="chip">Series: {data.series_count ?? 0}</span>
        <span className="chip">Errors: {data.errors?.length || 0}</span>
      </div>
      {(data.errors || []).length > 0 ? (
        <ul>
          {data.errors.map((item, idx) => <li key={idx}>{item}</li>)}
        </ul>
      ) : <p className="subtle">No source errors reported.</p>}
    </div>
  )
}

function StageSignals({ data }) {
  const selected = data.selected_signals || []
  const raw = data.raw_signals || []
  return (
    <div className="stageBody">
      <div className="chipRow">
        <span className="chip">Raw Signals: {raw.length}</span>
        <span className="chip">Selected: {selected.length}</span>
      </div>
      <p className="subtle">{data.filter_notes || 'LLM triage completed.'}</p>
      {selected.length ? (
        <ul>
          {selected.map((sig) => (
            <li key={sig.id}>
              <strong>{sig.type}</strong> - {sig.description}
            </li>
          ))}
        </ul>
      ) : <p className="subtle">No selected signals.</p>}
    </div>
  )
}

function StageHypotheses({ data }) {
  const rows = data.hypotheses || []
  return (
    <div className="stageBody">
      {rows.length ? rows.map((hyp, idx) => (
        <article key={hyp.id || idx} className="miniCard">
          <header>
            <h4>{hyp.title || `Hypothesis ${idx + 1}`}</h4>
            <span className="confidence">{String(hyp.confidence || 'n/a')}</span>
          </header>
          <p>{hyp.causal_story || 'No causal story provided.'}</p>
        </article>
      )) : <p className="subtle">No hypotheses generated.</p>}
    </div>
  )
}

function StageNews({ data }) {
  const rows = data.evidence_items || []
  return (
    <div className="stageBody">
      {rows.length ? rows.slice(0, 8).map((row, idx) => (
        <article key={`${row.url || row.title || idx}`} className="miniCard">
          <header>
            <h4>{row.source || row.source_domain || 'Source'}</h4>
            <span className="muted">{row.date || 'n/a'}</span>
          </header>
          <p>{row.summary || row.snippet || row.title || 'Evidence item.'}</p>
          <div className="muted">{row.stance ? `Stance: ${row.stance}` : ''}</div>
        </article>
      )) : <p className="subtle">No external evidence items returned.</p>}
    </div>
  )
}

function StageInsights({ data }) {
  const insights = data.insights || []
  const predictions = data.predictions || []
  return (
    <div className="stageBody">
      <div className="splitGrid">
        <div>
          <h4>Insights</h4>
          {insights.length ? (
            <ul>
              {insights.map((item, idx) => (
                <li key={item.id || idx}>
                  <strong>{item.headline || `Insight ${idx + 1}`}</strong>
                  <div className="subtle">{item.analysis || item.summary || 'No analysis text.'}</div>
                </li>
              ))}
            </ul>
          ) : <p className="subtle">No insights generated.</p>}
        </div>
        <div>
          <h4>Predictions</h4>
          {predictions.length ? (
            <ul>
              {predictions.map((item, idx) => (
                <li key={idx}>{summarizePrediction(item)}</li>
              ))}
            </ul>
          ) : <p className="subtle">No predictions generated.</p>}
        </div>
      </div>
    </div>
  )
}

function StageEvaluator({ data }) {
  return (
    <div className="stageBody">
      <div className="chipRow">
        <span className="chip">Score: {data.score ?? 'n/a'}</span>
      </div>
      <div className="splitGrid">
        <div>
          <h4>Strengths</h4>
          {(data.strengths || []).length ? <ul>{data.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul> : <p className="subtle">No strengths listed.</p>}
        </div>
        <div>
          <h4>Issues</h4>
          {(data.issues || []).length ? <ul>{data.issues.map((s, i) => <li key={i}>{s}</li>)}</ul> : <p className="subtle">No issues listed.</p>}
        </div>
      </div>
      {(data.revision_instructions || []).length ? (
        <>
          <h4>Revision Instructions</h4>
          <ul>{data.revision_instructions.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </>
      ) : null}
    </div>
  )
}

function StageBrief({ data }) {
  const markdown = data.brief_markdown || ''
  return (
    <div className="stageBody">
      {markdown ? (
        <div className="briefCard markdown">
          <ReactMarkdown>{markdown}</ReactMarkdown>
        </div>
      ) : (
        <p className="subtle">Final brief not available yet.</p>
      )}
    </div>
  )
}

function renderStageContent(stageKey, data) {
  switch (stageKey) {
    case 'data_fetch': return <StageDataFetch data={data} />
    case 'signal_extractor': return <StageSignals data={data} />
    case 'hypotheses_generator': return <StageHypotheses data={data} />
    case 'news_researcher': return <StageNews data={data} />
    case 'insights_generator_first_pass':
    case 'insights_generator':
      return <StageInsights data={data} />
    case 'evaluator': return <StageEvaluator data={data} />
    case 'brief_writer': return <StageBrief data={data} />
    default:
      return <p className="subtle">Stage output available.</p>
  }
}

export default function App() {
  const [activeTab, setActiveTab] = useState('pipeline')
  const [country, setCountry] = useState('SAU')
  const [startYear, setStartYear] = useState(2018)
  const [endYear, setEndYear] = useState(new Date().getFullYear())
  const [kpis, setKpis] = useState([])
  const [kpiId, setKpiId] = useState('')
  const [status, setStatus] = useState('Idle')
  const [error, setError] = useState('')
  const [generating, setGenerating] = useState(false)
  const [stageContent, setStageContent] = useState({})
  const [finalResult, setFinalResult] = useState(null)
  const [runHistory, setRunHistory] = useState([])
  const [selectedRunId, setSelectedRunId] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/kpis')
      .then((resp) => resp.json())
      .then((rows) => {
        if (cancelled) return
        setKpis(Array.isArray(rows) ? rows : [])
        if (rows?.[0]?.id) {
          setKpiId(rows[0].id)
        }
      })
      .catch(() => {
        if (!cancelled) setError('Failed to load KPI catalog.')
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const raw = localStorage.getItem(RUN_HISTORY_KEY)
    if (!raw) return
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        setRunHistory(parsed)
        if (parsed[0]?.id) setSelectedRunId(parsed[0].id)
      }
    } catch {
      // ignore malformed local storage
    }
  }, [])

  useEffect(() => {
    localStorage.setItem(RUN_HISTORY_KEY, JSON.stringify(runHistory.slice(0, 40)))
  }, [runHistory])

  const kpiName = useMemo(() => kpis.find((item) => item.id === kpiId)?.name || kpiId, [kpis, kpiId])
  const selectedRun = useMemo(() => runHistory.find((row) => row.id === selectedRunId) || null, [runHistory, selectedRunId])

  async function generateInsights() {
    if (!kpiId) {
      setError('Select a KPI.')
      return
    }
    if (startYear >= endYear) {
      setError('Start year must be less than end year.')
      return
    }

    setError('')
    setStatus('Starting...')
    setStageContent({})
    setFinalResult(null)
    setGenerating(true)

    try {
      const startedAt = new Date().toISOString()
      let streamRunId = `local-${Date.now()}`
      let stageCosts = {}

      const response = await fetch('/api/lab/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          country,
          start_year: Number(startYear),
          end_year: Number(endYear),
          kpi_id: kpiId,
        }),
      })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      if (!response.body) {
        throw new Error('No stream body returned by backend.')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let lineBuffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        lineBuffer += decoder.decode(value, { stream: true })
        const lines = lineBuffer.split('\n')
        lineBuffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          let event
          try {
            event = JSON.parse(trimmed)
          } catch {
            continue
          }
          if (event?.meta?.run_id) {
            streamRunId = event.meta.run_id
          }

          if (event.type === 'status') {
            setStatus(String(event.content || ''))
          } else if (event.type === 'stage' && event.stage) {
            setStageContent((prev) => ({ ...prev, [event.stage]: event.content }))
            if (event?.meta?.cost) {
              stageCosts = { ...stageCosts, [event.stage]: event.meta.cost }
            }
          } else if (event.type === 'result') {
            setFinalResult(event.content || null)
            if (event?.content?.stage_costs) {
              stageCosts = event.content.stage_costs
            }
          } else if (event.type === 'error') {
            setError(event.content?.message || 'Pipeline failed.')
          } else if (event.type === 'done') {
            setGenerating(false)
            if (event.content?.ok) {
              setStatus('Completed')
            } else {
              setStatus('Failed')
            }
            const doneCosts = event?.content?.stage_costs || stageCosts
            const doneTotal = Number(event?.content?.total_cost ?? Object.values(doneCosts).reduce((acc, item) => acc + Number(item?.total_cost || 0), 0))
            const finishedAt = new Date().toISOString()
            const runEntry = {
              id: event?.content?.run_id || streamRunId,
              status: event?.content?.ok ? 'completed' : 'failed',
              startedAt,
              finishedAt,
              country,
              kpiId,
              kpiName,
              startYear: Number(startYear),
              endYear: Number(endYear),
              totalCost: doneTotal,
              stageCosts: doneCosts,
            }
            setRunHistory((prev) => [runEntry, ...prev.filter((item) => item.id !== runEntry.id)].slice(0, 40))
            setSelectedRunId(runEntry.id)
          }
        }
      }
    } catch (err) {
      setError(err?.message || 'Generation failed.')
      setStatus('Failed')
      setGenerating(false)
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="page">
      <header className="hero">
        <div>
          <p className="eyebrow">Macro Brief</p>
          <h1>Insights Lab</h1>
          <p className="heroSub">Structured step-by-step pipeline view with run-level cost tracking.</p>
        </div>
        <div className={`status ${generating ? 'running' : ''}`}>{status}</div>
      </header>

      <section className="controls card">
        <label>
          Country
          <select value={country} onChange={(e) => setCountry(e.target.value)}>
            {COUNTRY_OPTIONS.map((code) => <option key={code} value={code}>{code}</option>)}
          </select>
        </label>
        <label>
          Start Year
          <input type="number" value={startYear} onChange={(e) => setStartYear(Number(e.target.value))} />
        </label>
        <label>
          End Year
          <input type="number" value={endYear} onChange={(e) => setEndYear(Number(e.target.value))} />
        </label>
        <label className="kpi">
          KPI
          <select value={kpiId} onChange={(e) => setKpiId(e.target.value)}>
            {kpis.map((item) => (
              <option key={item.id} value={item.id}>
                {item.id} - {item.name}
              </option>
            ))}
          </select>
        </label>
        <button className="run" onClick={generateInsights} disabled={generating || !kpiId}>
          {generating ? 'Generating...' : 'Generate Insights'}
        </button>
      </section>

      <section className="subtitle card">
        <strong>Run Context:</strong> {country} / {kpiName} / {startYear}-{endYear}
      </section>

      {error ? <section className="error">{error}</section> : null}

      <section className="tabs">
        <button className={activeTab === 'pipeline' ? 'active' : ''} onClick={() => setActiveTab('pipeline')}>Pipeline</button>
        <button className={activeTab === 'costs' ? 'active' : ''} onClick={() => setActiveTab('costs')}>Costs</button>
      </section>

      {activeTab === 'pipeline' ? (
        <section className="pipelineLayout">
          <section className="stageGrid">
            {STAGE_ORDER.map((stage, idx) => {
              const data = stageContent[stage.key]
              const done = stageState(stageContent, stage.key) === 'done'
              const cost = finalResult?.stage_costs?.[stage.key] || null
              return (
                <article key={stage.key} className={`stageCard ${done ? 'done' : 'pending'}`}>
                  <div className="stageHead">
                    <div>
                      <span className="stageIndex">{idx + 1}</span>
                      <h3>{stage.label}</h3>
                    </div>
                    {cost ? <span className="costTag">{currency(cost.total_cost)}</span> : null}
                  </div>
                  <p className="stageBlurb">{stage.blurb}</p>
                  {done ? renderStageContent(stage.key, data || {}) : <p className="pendingText">Waiting for output...</p>}
                </article>
              )
            })}
          </section>
          <aside className="summaryPane card">
            <h3>Run Summary</h3>
            <p className="subtle">Final output and cost telemetry for the latest run.</p>
            <div className="metricRow">
              <span>Total Cost</span>
              <strong>{currency(finalResult?.total_cost || 0)}</strong>
            </div>
            <div className="metricRow">
              <span>Run ID</span>
              <code>{finalResult?.run_id || '-'}</code>
            </div>
            <h4>Final Brief</h4>
            {finalResult?.brief_markdown ? (
              <div className="briefCard markdown">
                <ReactMarkdown>{finalResult.brief_markdown}</ReactMarkdown>
              </div>
            ) : (
              <p className="subtle">Final brief will appear after the brief writer stage completes.</p>
            )}
          </aside>
        </section>
      ) : (
        <section className="costsLayout">
          <article className="runsPane card">
            <h3>Runs</h3>
            {!runHistory.length ? <p className="subtle">No runs yet.</p> : null}
            <div className="runTable">
              {runHistory.map((run) => (
                <button
                  key={run.id}
                  className={`runRow ${selectedRunId === run.id ? 'active' : ''}`}
                  onClick={() => setSelectedRunId(run.id)}
                >
                  <div>
                    <strong>{run.country} - KPI {run.kpiId}</strong>
                    <p>{run.kpiName}</p>
                    <p className="muted">{run.startYear}-{run.endYear}</p>
                  </div>
                  <div className="runRowMeta">
                    <span>{currency(run.totalCost)}</span>
                    <span>{new Date(run.finishedAt).toLocaleString()}</span>
                  </div>
                </button>
              ))}
            </div>
          </article>
          <article className="costDetail card">
            <h3>Run Cost Breakdown</h3>
            {!selectedRun ? <p className="subtle">Select a run to view stage costs.</p> : (
              <>
                <div className="metricRow">
                  <span>Run ID</span>
                  <code>{selectedRun.id}</code>
                </div>
                <div className="metricRow">
                  <span>Status</span>
                  <strong>{selectedRun.status}</strong>
                </div>
                <div className="metricRow">
                  <span>Total</span>
                  <strong>{currency(selectedRun.totalCost)}</strong>
                </div>
                <table className="costTable">
                  <thead>
                    <tr>
                      <th>Stage</th>
                      <th>Model</th>
                      <th>Tokens (In/Out)</th>
                      <th>Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {STAGE_ORDER.map((stage) => {
                      const row = selectedRun.stageCosts?.[stage.key]
                      return (
                        <tr key={stage.key}>
                          <td>{stage.label}</td>
                          <td>{row?.model || '-'}</td>
                          <td>{row ? `${row.input_tokens || 0} / ${row.output_tokens || 0}` : '-'}</td>
                          <td>{currency(row?.total_cost || 0)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </>
            )}
          </article>
        </section>
      )}
    </div>
  )
}

