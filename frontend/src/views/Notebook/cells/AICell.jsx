import { useState, useRef } from 'react'
import { Brain, Send, Trash2, Wrench, Loader2 } from 'lucide-react'
import InsightSections from '../../../components/ui/InsightSections'
import useDataStore from '../../../stores/dataStore'

export default function AICell({ cell, onUpdate, onDelete, workspace }) {
  const [prompt, setPrompt] = useState(cell.metadata?.prompt || '')
  const [response, setResponse] = useState(cell.content || '')
  const [streaming, setStreaming] = useState(false)
  const [toolCalls, setToolCalls] = useState([])
  const inputRef = useRef(null)

  const handleSend = async () => {
    if (!prompt.trim() || streaming) return
    setStreaming(true)
    setResponse('')
    setToolCalls([])

    onUpdate(cell.id, '', { prompt })

    const { selectedCountries, selectedKpis, results } = useDataStore.getState()

    const context = {
      countries: selectedCountries,
      kpi_ids: selectedKpis,
    }
    if (results.length) {
      context.kpi_results = results.map(r => ({
        kpi_id: r.kpi_id,
        kpi_name: r.kpi_name,
        frequency: r.frequency,
        series: r.series?.map(s => ({
          country: s.country,
          indicator: s.indicator,
          points: s.points?.slice(-20),
        })) || [],
      }))
    }

    try {
      const resp = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: prompt,
          workspace_id: workspace?.id || '',
          cell_id: cell.id,
          context,
        }),
      })

      if (!resp.ok) {
        const errorBody = await resp.json().catch(() => ({}))
        throw new Error(errorBody.detail || `HTTP ${resp.status}`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let accumulated = ''
      let lineBuf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        lineBuf += decoder.decode(value, { stream: true })
        const parts = lineBuf.split('\n')
        lineBuf = parts.pop() ?? ''

        for (const line of parts) {
          const trimmed = line.trim()
          if (!trimmed) continue
          try {
            const chunk = JSON.parse(trimmed)
            if (chunk.type === 'text') {
              accumulated += chunk.content
              setResponse(accumulated)
            } else if (chunk.type === 'tool_call') {
              const toolInfo = JSON.parse(chunk.content)
              setToolCalls(prev => [...prev, { tool: toolInfo.tool, status: 'running' }])
            } else if (chunk.type === 'tool_result') {
              setToolCalls(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last) last.status = 'done'
                return updated
              })
            }
          } catch { /* malformed chunk */ }
        }
      }
      if (lineBuf.trim()) {
        try {
          const chunk = JSON.parse(lineBuf.trim())
          if (chunk.type === 'text') {
            accumulated += chunk.content
            setResponse(accumulated)
          }
        } catch { /* ignore */ }
      }

      onUpdate(cell.id, accumulated, { prompt })
    } catch (e) {
      setResponse(`Error: ${e.message}`)
    } finally {
      setStreaming(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="group rounded-xl border border-indigo-200 bg-white shadow-sm overflow-hidden hover:border-indigo-300 transition">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-indigo-100 bg-indigo-50/50">
        <Brain className="w-3.5 h-3.5 text-indigo-500" />
        <span className="text-[10px] font-medium text-indigo-500 uppercase tracking-wider">AI Research Assistant</span>
        <div className="flex-1" />
        <button onClick={() => onDelete(cell.id)}
          className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 transition">
          <Trash2 className="w-3 h-3 text-red-400" />
        </button>
      </div>

      <div className="px-4 py-3">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder="Ask about macro trends, compare countries, or request analysis… (Enter to send)"
            className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 resize-none outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400 placeholder:text-slate-300"
          />
          <button onClick={handleSend} disabled={streaming || !prompt.trim()}
            className="shrink-0 w-10 h-10 rounded-lg bg-indigo-600 text-white flex items-center justify-center hover:bg-indigo-700 disabled:opacity-40 transition self-end">
            {streaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>

        {toolCalls.length > 0 && (
          <div className="mt-3 space-y-1">
            {toolCalls.map((tc, i) => (
              <div key={i} className="flex items-center gap-2 text-[11px] text-indigo-600 bg-indigo-50 rounded-md px-2.5 py-1.5">
                <Wrench className="w-3 h-3" />
                <span>{tc.tool.replace(/_/g, ' ')}</span>
                {tc.status === 'running' && <Loader2 className="w-3 h-3 animate-spin ml-auto" />}
                {tc.status === 'done' && <span className="ml-auto text-green-600">done</span>}
              </div>
            ))}
          </div>
        )}

        {response && (
          <div className="mt-4 border-t border-slate-100 pt-3">
            <InsightSections text={response} />
          </div>
        )}
      </div>
    </div>
  )
}
