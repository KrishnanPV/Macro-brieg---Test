import { useState } from 'react'
import { Copy, Check } from 'lucide-react'

export default function ClipboardCopyButton({
  text,
  children = 'Copy',
  className = '',
  title,
  disabled = false,
}) {
  const [copied, setCopied] = useState(false)

  const handle = async () => {
    if (!text || disabled) return
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* noop */ }
  }

  return (
    <button
      type="button"
      onClick={handle}
      disabled={disabled || !text}
      title={title}
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition disabled:opacity-40 disabled:cursor-not-allowed ${className}`}
    >
      {copied ? <Check className="w-3.5 h-3.5 opacity-80" /> : <Copy className="w-3.5 h-3.5 opacity-80" />}
      {copied ? 'Copied' : children}
    </button>
  )
}
