import { useMemo } from 'react'
import type { MetricFields } from '../types'

interface TimelineEvent {
  id: string
  icon: string
  color: string
  message: string
  time: string
}

interface EventTimelineProps {
  metrics: Record<string, MetricFields>
}

/**
 * Derives "events" from current metric state for the MVP.
 * In the future this will come from a dedicated events API.
 */
function deriveEvents(metrics: Record<string, MetricFields>): TimelineEvent[] {
  const events: TimelineEvent[] = []
  const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

  const rtt = metrics['internet_rtt'] ?? {}
  const dns = metrics['dns_latency'] ?? {}
  const http = metrics['http_timing'] ?? {}

  const lossPct = rtt['loss_pct_mean'] as number | undefined
  if (lossPct != null && lossPct > 0) {
    events.push({ id: 'loss', icon: '!', color: 'text-red-400', message: `Packet loss detected: ${lossPct.toFixed(1)}%`, time: now })
  }

  const rttP95 = rtt['rtt_avg_ms_p95'] as number | undefined
  if (rttP95 != null && rttP95 > 50) {
    events.push({ id: 'rtt', icon: '\u2191', color: 'text-amber-400', message: `RTT p95 elevated: ${rttP95.toFixed(0)}ms`, time: now })
  }

  const dnsP95 = dns['latency_ms_p95'] as number | undefined
  if (dnsP95 != null && dnsP95 > 100) {
    events.push({ id: 'dns', icon: '\u2191', color: 'text-amber-400', message: `DNS p95 elevated: ${dnsP95.toFixed(0)}ms`, time: now })
  }

  const httpP95 = http['total_ms_p95'] as number | undefined
  if (httpP95 != null && httpP95 > 500) {
    events.push({ id: 'http', icon: '\u2191', color: 'text-amber-400', message: `HTTP p95 elevated: ${httpP95.toFixed(0)}ms`, time: now })
  }

  if (events.length === 0) {
    events.push({ id: 'ok', icon: '\u2713', color: 'text-emerald-400', message: 'All metrics within normal range', time: now })
  }

  return events
}

export default function EventTimeline({ metrics }: EventTimelineProps) {
  const events = useMemo(() => deriveEvents(metrics), [metrics])

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h3 className="text-sm font-medium text-slate-300 mb-3">Event Timeline</h3>
      <div className="flex flex-col gap-2 max-h-48 overflow-y-auto">
        {events.map((ev) => (
          <div key={ev.id} className="flex items-start gap-2 text-xs">
            <span className={`${ev.color} font-bold w-4 text-center flex-shrink-0`}>{ev.icon}</span>
            <span className="text-slate-300 flex-1">{ev.message}</span>
            <span className="text-slate-600 flex-shrink-0">{ev.time}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
