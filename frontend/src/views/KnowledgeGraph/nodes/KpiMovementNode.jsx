import { Handle, Position } from '@xyflow/react'
import { TrendingUp } from 'lucide-react'

export default function KpiMovementNode({ data }) {
  return (
    <div className="rounded-xl bg-blue-50 border-2 border-blue-300 px-4 py-3 min-w-[140px] shadow-sm">
      <Handle type="target" position={Position.Top} className="!bg-blue-500" />
      <div className="flex items-center gap-2">
        <TrendingUp className="w-4 h-4 text-blue-600" />
        <span className="text-xs font-semibold text-blue-800">{data.label}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-blue-500" />
    </div>
  )
}
