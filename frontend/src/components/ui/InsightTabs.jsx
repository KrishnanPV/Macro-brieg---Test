export default function InsightTabs({ tabs, activeTab, onTabChange, children }) {
  return (
    <div className="rounded-xl border border-mck-pale/40 overflow-hidden">
      <div className="flex items-end gap-0 px-1.5 pt-1.5 bg-gradient-to-b from-mck-blue/5 to-mck-blue/10">
        {tabs.map((tab) => {
          const isActive = tab.key === activeTab
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => onTabChange(tab.key)}
              className={`
                relative px-4 py-2 text-[11px] font-semibold transition-all duration-200
                ${isActive
                  ? 'bg-white text-mck-navy rounded-t-lg shadow-sm z-10'
                  : 'text-mck-deep/60 hover:text-mck-deep hover:bg-white/50 rounded-t-lg'
                }
              `}
              style={isActive ? {
                marginBottom: '-1px',
                paddingBottom: 'calc(0.5rem + 1px)',
                borderTop: '2px solid #24477F',
                borderLeft: '1px solid #A8BFD0',
                borderRight: '1px solid #A8BFD0',
              } : {}}
            >
              {tab.label}
              {tab.loading && (
                <span className="inline-block ml-1.5 h-2.5 w-2.5 rounded-full border-2 border-mck-sky border-t-transparent animate-spin align-middle" />
              )}
            </button>
          )
        })}
      </div>

      <div className="bg-white border-t border-mck-pale/40">
        <div className="px-5 py-4">
          {children}
        </div>
      </div>
    </div>
  )
}
