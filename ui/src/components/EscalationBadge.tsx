import type { EscalationData } from '../types'

const STATE_COLORS: Record<string, string> = {
  BASELINE: 'bg-emerald-400',
  ELEVATED: 'bg-amber-400',
  ACTIVE: 'bg-red-400',
  COOLDOWN: 'bg-blue-400',
}

export default function EscalationBadge({ escalation }: { escalation: EscalationData }) {
  const dotColor = STATE_COLORS[escalation.state] ?? 'bg-slate-400'

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${dotColor}`} />
      <span className="text-slate-300 font-medium">{escalation.state}</span>
    </div>
  )
}
