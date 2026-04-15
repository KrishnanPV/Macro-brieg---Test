import { Handle, Position } from '@xyflow/react'
import { Lightbulb } from 'lucide-react'

export default function InsightNode({ data }) {
  return (
    <div className="rounded-xl bg-purple-50 border-2 border-purple-300 px-4 py-3 min-w-[160px] max-w-[220px] shadow-sm">
      <Handle type="target" position={Position.Top} className="!bg-purple-500" />
      <div className="flex items-start gap-2">
        <Lightbulb className="w-4 h-4 text-purple-600 shrink-0 mt-0.5" />
        <span className="text-xs text-purple-800 leading-snug">{data.label}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-purple-500" />
    </div>
  )
}
