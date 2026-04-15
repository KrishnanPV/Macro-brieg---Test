import { useNavigate } from 'react-router-dom'
import { Flag, LayoutDashboard, ArrowRight } from 'lucide-react'

const cards = [
  {
    to: '/country-brief',
    icon: Flag,
    title: 'Country Brief',
    subtitle: 'Automated single-country macro analysis across all KPIs',
    description: 'Select a country and instantly load every available macro-economic indicator. Generate AI-powered insights with a single click.',
    gradient: 'from-blue-600 to-indigo-700',
    hoverGradient: 'hover:from-blue-700 hover:to-indigo-800',
    shadow: 'shadow-blue-600/20 hover:shadow-blue-700/30',
    iconBg: 'bg-blue-500/20',
    delay: '150ms',
  },
  {
    to: '/dashboard',
    icon: LayoutDashboard,
    title: 'Customizable Dashboard',
    subtitle: 'Build your own multi-country, multi-KPI view',
    description: 'Choose any combination of countries and KPIs. Compare across economies with interactive charts and tabbed insights.',
    gradient: 'from-purple-600 to-fuchsia-700',
    hoverGradient: 'hover:from-purple-700 hover:to-fuchsia-800',
    shadow: 'shadow-purple-600/20 hover:shadow-purple-700/30',
    iconBg: 'bg-purple-500/20',
    delay: '300ms',
  },
]

export default function Landing() {
  const navigate = useNavigate()

  return (
    <div className="h-full flex flex-col items-center justify-center px-6 overflow-hidden"
      style={{ background: 'linear-gradient(135deg, #f8fafc 0%, #eef2ff 50%, #f5f3ff 100%)' }}>

      <div className="text-center mb-12 animate-[fadeSlideUp_0.6s_ease-out_both]">
        <h1 className="text-3xl font-extrabold text-slate-800 tracking-tight mb-3">
          Macro Brief
        </h1>
        <p className="text-base text-slate-500 max-w-lg mx-auto leading-relaxed">
          AI-powered macroeconomic analysis and country intelligence, grounded in Oxford Economics data.
        </p>
      </div>

      <div className="flex flex-col md:flex-row gap-6 max-w-3xl w-full">
        {cards.map((card) => {
          const Icon = card.icon
          return (
            <button
              key={card.to}
              onClick={() => navigate(card.to)}
              className={`
                group flex-1 relative rounded-2xl p-8 text-left text-white
                bg-gradient-to-br ${card.gradient} ${card.hoverGradient}
                shadow-xl ${card.shadow}
                transition-all duration-300 ease-out
                hover:scale-[1.03] hover:-translate-y-1
                active:scale-[0.99]
                animate-[fadeSlideUp_0.6s_ease-out_both]
              `}
              style={{ animationDelay: card.delay }}
            >
              <div className={`inline-flex items-center justify-center w-12 h-12 rounded-xl ${card.iconBg} mb-5`}>
                <Icon className="w-6 h-6" />
              </div>

              <h2 className="text-xl font-bold mb-1">{card.title}</h2>
              <p className="text-sm font-medium opacity-80 mb-3">{card.subtitle}</p>
              <p className="text-xs opacity-60 leading-relaxed mb-6">{card.description}</p>

              <div className="flex items-center gap-1.5 text-xs font-semibold opacity-70 group-hover:opacity-100 transition-opacity">
                Get started <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-1" />
              </div>
            </button>
          )
        })}
      </div>

      <style>{`
        @keyframes fadeSlideUp {
          from {
            opacity: 0;
            transform: translateY(24px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
      `}</style>
    </div>
  )
}
