import { Compass, MessageSquare, Wind, ShieldAlert, Scale } from 'lucide-react'
import { parseMarkdownBlocks } from '../../../components/ui/InsightSections'

function splitOutlookSections(content) {
  const tw = { title: 'Tailwinds', icon: Wind, content: '', color: 'emerald' }
  const hw = { title: 'Headwinds', icon: ShieldAlert, content: '', color: 'red' }
  const na = { title: 'Net Assessment', icon: Scale, content: '', color: 'blue' }

  const sections = [tw, hw, na]
  const markers = [
    { re: /\*\*Tailwinds\*\*/i, sec: tw },
    { re: /\*\*Headwinds\*\*/i, sec: hw },
    { re: /\*\*Net Assessment\*\*/i, sec: na },
  ]

  const lines = content.split('\n')
  let current = null

  for (const line of lines) {
    let matched = false
    for (const { re, sec } of markers) {
      if (re.test(line)) {
        current = sec
        matched = true
        break
      }
    }
    if (!matched && current) {
      current.content += line + '\n'
    }
  }

  const populated = sections.filter(s => s.content.trim())
  return populated.length > 0 ? populated : null
}

const COLOR_MAP = {
  emerald: {
    border: 'border-emerald-200/60',
    bg: 'bg-emerald-50/50',
    iconBg: 'bg-emerald-100',
    iconText: 'text-emerald-600',
    titleText: 'text-emerald-800',
  },
  red: {
    border: 'border-red-200/60',
    bg: 'bg-red-50/40',
    iconBg: 'bg-red-100',
    iconText: 'text-red-600',
    titleText: 'text-red-800',
  },
  blue: {
    border: 'border-blue-200/60',
    bg: 'bg-blue-50/40',
    iconBg: 'bg-blue-100',
    iconText: 'text-blue-600',
    titleText: 'text-blue-800',
  },
}

export default function OutlookBlock({ content, blockIndex, onDiscuss, newsCatalog = [] }) {
  const parsed = splitOutlookSections(content)

  if (!parsed) {
    return (
      <div className="group relative rounded-2xl border border-amber-200/60 bg-gradient-to-br from-amber-50/40 to-orange-50/20 shadow-sm overflow-hidden">
        <div className="px-6 py-5">
          <OutlookHeader onDiscuss={onDiscuss} blockIndex={blockIndex} content={content} />
          <div className="text-[13.5px] text-slate-700 leading-[1.75] space-y-3">
            {parseMarkdownBlocks(content, newsCatalog)}
          </div>
        </div>
      </div>
    )
  }

  const twHw = parsed.filter(s => s.title !== 'Net Assessment')
  const netAssessment = parsed.find(s => s.title === 'Net Assessment')

  return (
    <div className="group relative space-y-4">
      <div className="flex items-center justify-between">
        <OutlookHeader onDiscuss={onDiscuss} blockIndex={blockIndex} content={content} />
      </div>

      {twHw.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {twHw.map(sec => {
            const c = COLOR_MAP[sec.color]
            const Icon = sec.icon
            return (
              <div key={sec.title} className={`rounded-xl border ${c.border} ${c.bg} p-5 shadow-sm`}>
                <div className="flex items-center gap-2 mb-3">
                  <div className={`w-7 h-7 rounded-lg ${c.iconBg} flex items-center justify-center`}>
                    <Icon className={`w-3.5 h-3.5 ${c.iconText}`} />
                  </div>
                  <h3 className={`text-xs font-bold uppercase tracking-wider ${c.titleText}`}>
                    {sec.title}
                  </h3>
                </div>
                <div className="text-[13px] text-slate-700 leading-[1.7] space-y-2">
                  {parseMarkdownBlocks(sec.content.trim(), newsCatalog)}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {netAssessment && (
        <div className={`rounded-xl border ${COLOR_MAP.blue.border} ${COLOR_MAP.blue.bg} p-5 shadow-sm`}>
          <div className="flex items-center gap-2 mb-3">
            <div className={`w-7 h-7 rounded-lg ${COLOR_MAP.blue.iconBg} flex items-center justify-center`}>
              <Scale className={`w-3.5 h-3.5 ${COLOR_MAP.blue.iconText}`} />
            </div>
            <h3 className={`text-xs font-bold uppercase tracking-wider ${COLOR_MAP.blue.titleText}`}>
              Net Assessment
            </h3>
          </div>
          <div className="text-[13px] text-slate-700 leading-[1.7] space-y-2">
            {parseMarkdownBlocks(netAssessment.content.trim(), newsCatalog)}
          </div>
        </div>
      )}
    </div>
  )
}

function OutlookHeader({ onDiscuss, blockIndex, content }) {
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center">
          <Compass className="w-4 h-4 text-amber-700" />
        </div>
        <h2 className="text-sm font-bold text-amber-800 uppercase tracking-wider">
          Forward Outlook
        </h2>
      </div>
      {onDiscuss && (
        <button
          onClick={() => onDiscuss(blockIndex, 'Forward Outlook', content)}
          className="opacity-0 group-hover:opacity-100 transition-opacity inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-slate-500 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:text-mck-navy"
        >
          <MessageSquare className="w-3 h-3" />Discuss
        </button>
      )}
    </div>
  )
}
