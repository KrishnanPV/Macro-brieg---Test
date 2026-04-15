import { useMemo } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { SERIES_COLORS } from '../../../lib/colors'
import { formatAbbrevNumber, formatAxisTick } from '../../../lib/formatNumbers'

const SCALE_WORDS = {
  billions: 1e9, billion: 1e9,
  millions: 1e6, million: 1e6,
  thousands: 1e3, thousand: 1e3,
}

function getScaleMultiplier(unit) {
  if (!unit) return 1
  for (const token of unit.toLowerCase().split(/\s+/)) {
    if (SCALE_WORDS[token]) return SCALE_WORDS[token]
  }
  return 1
}

function isoToQuarterLabel(d) {
  const dt = new Date(d)
  const q = Math.floor(dt.getMonth() / 3) + 1
  return `Q${q} ${dt.getFullYear()}`
}

function isoToYearLabel(d) {
  return new Date(d).getFullYear().toString()
}

function quarterlyAxisLabel(d) {
  const dt = new Date(d)
  const q = Math.floor(dt.getMonth() / 3) + 1
  return q === 1 ? dt.getFullYear().toString() : ''
}

function computeAnnualTicks(rows, maxTicks = 15) {
  if (rows.length <= maxTicks) return rows.map(r => r.date)
  const step = Math.ceil(rows.length / maxTicks)
  return rows.filter((_, i) => i % step === 0).map(r => r.date)
}

function CustomTooltip({ active, payload, label, dateFormatter }) {
  if (!active || !payload?.length) return null
  const fmt = dateFormatter || isoToYearLabel
  return (
    <div className="bg-white rounded-lg shadow-lg border border-slate-200 px-3 py-2 text-xs">
      <p className="font-semibold text-slate-800 mb-1">{fmt(label)}</p>
      {payload.map((entry, i) => (
        <div key={i} className="flex items-center gap-2 py-0.5">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: entry.color }} />
          <span className="text-slate-500 truncate max-w-[160px]">{entry.name}</span>
          <span className="ml-auto font-mono font-medium text-slate-800">
            {formatAbbrevNumber(entry.value)}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function InlineChartBlock({ kpiId, kpiDataCache = [], compact = false }) {
  const kpiResult = kpiDataCache.find(r => String(r.kpi_id) === String(kpiId))
  const isQuarterly = kpiResult?.frequency === 'Q'

  const { seriesKeys, rows, kpiName } = useMemo(() => {
    if (!kpiResult || !kpiResult.series?.length) {
      return { seriesKeys: [], rows: [], kpiName: '' }
    }

    const dateMap = new Map()
    const keys = []
    kpiResult.series.forEach((s, idx) => {
      const key = s.indicator
      const mult = getScaleMultiplier(s.unit || kpiResult.unit || '')
      keys.push({ key, color: SERIES_COLORS[idx % SERIES_COLORS.length] })
      s.points.forEach(p => {
        if (p.value == null) return
        if (!dateMap.has(p.date)) dateMap.set(p.date, { date: p.date })
        dateMap.get(p.date)[key] = p.value * mult
      })
    })

    return {
      seriesKeys: keys,
      rows: Array.from(dateMap.values()).sort((a, b) => a.date.localeCompare(b.date)),
      kpiName: kpiResult.kpi_name,
    }
  }, [kpiResult])

  if (!rows.length) return null

  const chartHeight = compact ? 180 : 220
  const tooltipFmt = isQuarterly ? isoToQuarterLabel : isoToYearLabel
  const axisFmt = isQuarterly ? quarterlyAxisLabel : isoToYearLabel
  const ticks = isQuarterly ? rows.map(r => r.date) : computeAnnualTicks(rows)

  return (
    <div className={compact
      ? "rounded-lg overflow-hidden"
      : "my-4 rounded-xl border border-slate-200/80 bg-white shadow-sm overflow-hidden"
    }>
      <div className={compact
        ? "px-3 py-2 border-b border-slate-100/60"
        : "px-4 py-3 border-b border-slate-100 bg-slate-50/50"
      }>
        <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
          {kpiName}
        </p>
      </div>
      <div className={compact ? "px-2 py-2" : "px-4 py-3"}>
        <ResponsiveContainer width="100%" height={chartHeight}>
          <AreaChart data={rows}>
            <defs>
              {seriesKeys.map(sk => (
                <linearGradient key={sk.key} id={`brief-grad-${kpiId}-${sk.key.replace(/\W/g, '_')}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={sk.color} stopOpacity={0.15} />
                  <stop offset="95%" stopColor={sk.color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis
              dataKey="date"
              tickFormatter={axisFmt}
              ticks={ticks}
              tick={{ fontSize: 10, fill: '#94a3b8' }} height={24}
              axisLine={{ stroke: '#e2e8f0' }}
            />
            <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={formatAxisTick} axisLine={false} tickLine={false} width={52} />
            <Tooltip content={<CustomTooltip dateFormatter={tooltipFmt} />} />
            {seriesKeys.map(sk => (
              <Area
                key={sk.key} type="monotone" dataKey={sk.key} stroke={sk.color}
                fill={`url(#brief-grad-${kpiId}-${sk.key.replace(/\W/g, '_')})`}
                strokeWidth={2} dot={false}
                activeDot={{ r: 3, strokeWidth: 2, fill: '#fff' }}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
        {seriesKeys.length > 1 && (
          <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 pt-1 text-[10px]">
            {seriesKeys.map(sk => (
              <div key={sk.key} className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: sk.color }} />
                <span className="text-slate-500">{sk.key}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
