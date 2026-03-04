import type { MetricFields, SparklinesResponse } from '../types'
import MetricCard from './MetricCard'

interface MetricGridProps {
  metrics: Record<string, MetricFields>
  sparklines: SparklinesResponse | null
}

export default function MetricGrid({ metrics, sparklines }: MetricGridProps) {
  const rtt = metrics['internet_rtt'] ?? {}
  const dns = metrics['dns_latency'] ?? {}
  const http = metrics['http_timing'] ?? {}
  const device = metrics['device_health'] ?? {}
  const sp = sparklines?.sparklines ?? {}

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
      <MetricCard
        label="Internet RTT"
        value={rtt['rtt_avg_ms_mean'] as number | null}
        unit="ms"
        p95={rtt['rtt_avg_ms_p95'] as number | null}
        sparkData={sp['internet_rtt'] ?? []}
        lowerIsBetter
      />
      <MetricCard
        label="DNS Latency"
        value={dns['latency_ms_mean'] as number | null}
        unit="ms"
        p95={dns['latency_ms_p95'] as number | null}
        sparkData={sp['dns_latency'] ?? []}
        lowerIsBetter
      />
      <MetricCard
        label="HTTP Timing"
        value={http['total_ms_mean'] as number | null}
        unit="ms"
        p95={http['total_ms_p95'] as number | null}
        sparkData={sp['http_timing'] ?? []}
        lowerIsBetter
      />
      <MetricCard
        label="Packet Loss"
        value={rtt['loss_pct_mean'] as number | null}
        unit="%"
        sparkData={sp['packet_loss'] ?? []}
        lowerIsBetter
      />
      <MetricCard
        label="CPU"
        value={device['cpu_percent_mean'] as number | null}
        unit="%"
        sparkData={sp['cpu'] ?? []}
        lowerIsBetter
      />
      <MetricCard
        label="Memory"
        value={device['memory_percent_mean'] as number | null}
        unit="%"
        sparkData={sp['memory'] ?? []}
        lowerIsBetter
      />
    </div>
  )
}
