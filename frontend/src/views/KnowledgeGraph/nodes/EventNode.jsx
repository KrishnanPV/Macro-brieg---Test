import { Handle, Position } from '@xyflow/react'
import { Zap } from 'lucide-react'

export default function EventNode({ data }) {
  return (
    <div className="rounded-xl bg-red-50 border-2 border-red-300 px-4 py-3 min-w-[140px] shadow-sm">
      <Handle type="target" position={Position.Top} className="!bg-red-500" />
      <div className="flex items-center gap-2">
        <Zap className="w-4 h-4 text-red-600" />
        <span className="text-xs font-semibold text-red-800">{data.label}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-red-500" />
    </div>
  )
}
