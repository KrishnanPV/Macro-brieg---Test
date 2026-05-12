import { useState, useRef, useEffect } from 'react'
import { X, Send, Loader2, Check, ChevronUp, ChevronDown } from 'lucide-react'
import { parseMarkdownBlocks } from '../../components/ui/InsightSections'
import useCountryBriefStore from '../../stores/countryBriefStore'

export default function BriefSidebar({ docked = false }) {
  const {
    sidebarOpen, activeSectionIndex, activeSectionTitle, activeSectionContent,
    sidebarHistory, kpiDataCache,
    closeSidebar, addSidebarMessage, updateBlockContent,
  } = useCountryBriefStore()

  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamedResponse, setStreamedResponse] = useState('')
  const [showApply, setShowApply] = useState(false)
  const [dockedExpanded, setDockedExpanded] = useState(false)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  const historyKey = String(activeSectionIndex)
  const messages = sidebarHistory[historyKey] || []

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamedResponse])

  useEffect(() => {
    if (sidebarOpen && inputRef.current) {
      inputRef.current.focus()
    }
  }, [sidebarOpen, activeSectionIndex])

  useEffect(() => {
    if (sidebarOpen && docked) setDockedExpanded(true)
  }, [sidebarOpen, docked])

  const handleSend = async () => {
    if (!input.trim() || streaming) return

    const userMessage = input.trim()
    setInput('')
    setStreamedResponse('')
    setShowApply(false)
    setStreaming(true)

    addSidebarMessage(activeSectionIndex, 'user', userMessage)

    try {
      const resp = await fetch('/api/country-brief/refine', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          section_content: activeSectionContent,
          data_context: {
            kpi_data: kpiDataCache?.slice(0, 5),
          },
          message: userMessage,
          history: messages.map(m => ({ role: m.role, content: m.content })),
        }),
      })

      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}))
        throw new Error(detail.detail || `HTTP ${resp.status}`)
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
              setStreamedResponse(accumulated)
            }
          } catch { /* malformed */ }
        }
      }

      if (accumulated) {
        addSidebarMessage(activeSectionIndex, 'assistant', accumulated)
        setShowApply(true)
      }
    } catch (e) {
      addSidebarMessage(activeSectionIndex, 'assistant', `Error: ${e.message}`)
    } finally {
      setStreaming(false)
      setStreamedResponse('')
    }
  }

  const handleApply = () => {
    const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
    if (lastAssistant) {
      updateBlockContent(activeSectionIndex, lastAssistant.content)
      setShowApply(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  /* ─── Docked variant: compact chat at the bottom of the right column ─── */
  if (docked) {
    if (!sidebarOpen) return null

    return (
      <div className={`shrink-0 border-t border-slate-200 bg-white flex flex-col transition-all duration-200 ${dockedExpanded ? 'max-h-[40%]' : 'max-h-12'}`}>
        {/* Docked header — click to expand/collapse */}
        <button
          type="button"
          onClick={() => setDockedExpanded(v => !v)}
          className="flex items-center justify-between px-4 py-2 shrink-0 hover:bg-slate-50 transition"
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Refine</span>
            <span className="text-[11px] text-slate-600 font-medium truncate">{activeSectionTitle}</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); closeSidebar() }}
              className="p-1 rounded hover:bg-slate-200 text-slate-400 hover:text-slate-600 transition"
            >
              <X className="w-3 h-3" />
            </button>
            {dockedExpanded ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronUp className="w-3.5 h-3.5 text-slate-400" />}
          </div>
        </button>

        {dockedExpanded && (
          <>
            {/* Chat messages */}
            <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2 min-h-0">
              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] rounded-lg px-3 py-2 text-[11.5px] leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-mck-navy text-white'
                      : 'bg-slate-100 text-slate-700'
                  }`}>
                    {msg.role === 'assistant' ? (
                      <div className="space-y-1">{parseMarkdownBlocks(msg.content)}</div>
                    ) : (
                      msg.content
                    )}
                  </div>
                </div>
              ))}

              {streaming && streamedResponse && (
                <div className="flex justify-start">
                  <div className="max-w-[85%] rounded-lg px-3 py-2 text-[11.5px] leading-relaxed bg-slate-100 text-slate-700">
                    <div className="space-y-1">{parseMarkdownBlocks(streamedResponse)}</div>
                  </div>
                </div>
              )}

              {streaming && !streamedResponse && (
                <div className="flex justify-start">
                  <div className="rounded-lg px-3 py-2 bg-slate-100 flex items-center gap-2">
                    <Loader2 className="w-3 h-3 animate-spin text-slate-400" />
                    <span className="text-[11px] text-slate-400">Thinking...</span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Apply */}
            {showApply && (
              <div className="px-3 py-1.5 shrink-0">
                <button
                  onClick={handleApply}
                  className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-[11px] font-semibold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 transition"
                >
                  <Check className="w-3 h-3" />Apply Revision
                </button>
              </div>
            )}

            {/* Input */}
            <div className="px-3 py-2 border-t border-slate-100 shrink-0">
              <div className="flex gap-1.5">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  rows={1}
                  placeholder="Revise this section... (Enter to send)"
                  className="flex-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[12px] text-slate-700 resize-none outline-none focus:border-mck-blue focus:ring-1 focus:ring-mck-blue placeholder:text-slate-300"
                />
                <button
                  onClick={handleSend}
                  disabled={streaming || !input.trim()}
                  className="shrink-0 w-8 h-8 rounded-lg bg-mck-navy text-white flex items-center justify-center hover:bg-mck-deep disabled:opacity-40 transition self-end"
                >
                  {streaming ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    )
  }

  /* ─── Classic full-height sidebar (used in free-scroll view) ─── */
  if (!sidebarOpen) return null

  return (
    <aside className="w-96 shrink-0 border-l border-slate-200 bg-white flex flex-col h-full">
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between shrink-0">
        <div className="min-w-0">
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Refine Section</h3>
          <p className="text-sm font-medium text-mck-navy truncate mt-0.5">{activeSectionTitle}</p>
        </div>
        <button onClick={closeSidebar}
          className="p-1.5 rounded-md hover:bg-slate-100 transition text-slate-400 hover:text-slate-600">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/50 shrink-0 max-h-28 overflow-y-auto">
        <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Current text</p>
        <p className="text-[11px] text-slate-500 leading-relaxed line-clamp-4">
          {activeSectionContent?.slice(0, 300)}{activeSectionContent?.length > 300 ? '...' : ''}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-[12.5px] leading-relaxed ${
              msg.role === 'user'
                ? 'bg-mck-navy text-white'
                : 'bg-slate-100 text-slate-700'
            }`}>
              {msg.role === 'assistant' ? (
                <div className="space-y-1.5">{parseMarkdownBlocks(msg.content)}</div>
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}

        {streaming && streamedResponse && (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-xl px-3.5 py-2.5 text-[12.5px] leading-relaxed bg-slate-100 text-slate-700">
              <div className="space-y-1.5">{parseMarkdownBlocks(streamedResponse)}</div>
            </div>
          </div>
        )}

        {streaming && !streamedResponse && (
          <div className="flex justify-start">
            <div className="rounded-xl px-3.5 py-2.5 bg-slate-100 flex items-center gap-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" />
              <span className="text-[12px] text-slate-400">Thinking...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {showApply && (
        <div className="px-4 py-2 border-t border-slate-100 shrink-0">
          <button
            onClick={handleApply}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 text-xs font-semibold text-white bg-emerald-600 rounded-xl hover:bg-emerald-700 transition shadow-sm"
          >
            <Check className="w-3.5 h-3.5" />Apply Revision to Brief
          </button>
        </div>
      )}

      <div className="px-4 py-3 border-t border-slate-100 shrink-0">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder="Ask to revise this section... (Enter to send)"
            className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 resize-none outline-none focus:border-mck-blue focus:ring-1 focus:ring-mck-blue placeholder:text-slate-300"
          />
          <button
            onClick={handleSend}
            disabled={streaming || !input.trim()}
            className="shrink-0 w-9 h-9 rounded-lg bg-mck-navy text-white flex items-center justify-center hover:bg-mck-deep disabled:opacity-40 transition self-end"
          >
            {streaming ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>
    </aside>
  )
}
