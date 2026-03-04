import { formatRelativeTime } from '../lib/format'

interface FooterProps {
  probeId: string
  version: string
  lastUpdated: Date | null
}

export default function Footer({ probeId, version, lastUpdated }: FooterProps) {
  return (
    <footer className="border-t border-slate-800 px-6 py-3 flex items-center justify-between text-xs text-slate-500">
      <div className="flex items-center gap-3">
        <span className="font-mono">{probeId}</span>
        <span className="text-slate-700">|</span>
        <span>v{version}</span>
      </div>
      <div>
        Last update: {formatRelativeTime(lastUpdated)}
      </div>
    </footer>
  )
}
