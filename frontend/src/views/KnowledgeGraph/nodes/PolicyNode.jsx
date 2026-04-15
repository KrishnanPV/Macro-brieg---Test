import { Handle, Position } from '@xyflow/react'
import { Shield } from 'lucide-react'

export default function PolicyNode({ data }) {
  return (
    <div className="rounded-xl bg-green-50 border-2 border-green-300 px-4 py-3 min-w-[140px] shadow-sm">
      <Handle type="target" position={Position.Top} className="!bg-green-500" />
      <div className="flex items-center gap-2">
        <Shield className="w-4 h-4 text-green-600" />
        <span className="text-xs font-semibold text-green-800">{data.label}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-green-500" />
    </div>
  )
}
