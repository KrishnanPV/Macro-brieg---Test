/** Annual vs quarterly resolution for KPI charts (shared by Dashboard + Country Brief). */
export default function ChartFrequencyToggle({ value, loading, onChange, wide }) {
  const isQ = value === 'Q'
  return (
    <div className={`inline-flex rounded-lg overflow-hidden border border-slate-200 ${wide ? 'w-full' : ''}`}>
      <button
        type="button"
        disabled={loading}
        onClick={() => onChange('A')}
        className={`px-2.5 py-1.5 text-[12px] font-medium transition-all ${
          wide ? 'flex-1' : ''
        } ${!isQ ? 'bg-mck-navy text-white' : 'bg-white text-slate-500 hover:bg-slate-50'} ${
          loading ? 'opacity-50 cursor-wait' : ''
        }`}
      >
        Annual
      </button>
      <button
        type="button"
        disabled={loading}
        onClick={() => onChange('Q')}
        className={`px-2.5 py-1.5 text-[12px] font-medium transition-all border-l border-slate-200 ${
          wide ? 'flex-1' : ''
        } ${isQ ? 'bg-mck-navy text-white' : 'bg-white text-slate-500 hover:bg-slate-50'} ${
          loading ? 'opacity-50 cursor-wait' : ''
        }`}
      >
        Quarterly
      </button>
    </div>
  )
}
