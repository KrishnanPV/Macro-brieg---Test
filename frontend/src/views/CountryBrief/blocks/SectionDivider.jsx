export default function SectionDivider({ title }) {
  return (
    <div className="flex items-center gap-4 pt-8 pb-4">
      <div className="h-px flex-1 bg-gradient-to-r from-transparent via-slate-300 to-transparent" />
      <h2 className="text-xs font-bold text-mck-navy uppercase tracking-[0.15em] whitespace-nowrap">
        {title}
      </h2>
      <div className="h-px flex-1 bg-gradient-to-r from-transparent via-slate-300 to-transparent" />
    </div>
  )
}
