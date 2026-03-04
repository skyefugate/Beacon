import { formatNumber, formatUptime } from '../lib/format'
import type { AgentInfo, MetricFields } from '../types'

interface SystemHealthProps {
  device: MetricFields
  agent: AgentInfo
}

function ProgressBar({ label, value, max = 100 }: { label: string; value: number; max?: number }) {
  const pct = Math.min((value / max) * 100, 100)
  const color = pct > 80 ? 'bg-red-400' : pct > 50 ? 'bg-amber-400' : 'bg-cyan-400'

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-slate-400 w-10">{label}</span>
      <div className="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-300 w-12 text-right font-mono">{formatNumber(value)}%</span>
    </div>
  )
}

export default function SystemHealth({ device, agent }: SystemHealthProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h3 className="text-sm font-medium text-slate-300 mb-4">System Health</h3>
      <div className="flex flex-col gap-3">
        <ProgressBar label="CPU" value={device['cpu_percent_mean'] as number ?? 0} />
        <ProgressBar label="MEM" value={device['memory_percent_mean'] as number ?? 0} />
        {device['disk_percent_mean'] != null && (
          <ProgressBar label="Disk" value={device['disk_percent_mean'] as number} />
        )}
        <div className="pt-2 border-t border-slate-800 text-xs text-slate-400">
          Uptime: <span className="text-slate-300 font-mono">{formatUptime(agent.uptime_seconds)}</span>
        </div>
      </div>
    </div>
  )
}
