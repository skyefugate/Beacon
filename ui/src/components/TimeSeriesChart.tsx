import ReactECharts from 'echarts-for-react'
import { useMemo, useState } from 'react'
import { useSeries } from '../hooks/useSeries'
import type { TimeRange } from '../types'

const MEASUREMENTS = [
  { value: 'internet_rtt', label: 'Internet RTT' },
  { value: 'dns_latency', label: 'DNS Latency' },
  { value: 'http_timing', label: 'HTTP Timing' },
  { value: 'device_health', label: 'Device Health' },
] as const

const FIELDS: Record<string, { value: string; label: string }[]> = {
  internet_rtt: [
    { value: 'rtt_avg_ms_mean', label: 'RTT Mean' },
    { value: 'rtt_avg_ms_p95', label: 'RTT p95' },
    { value: 'rtt_avg_ms_p99', label: 'RTT p99' },
    { value: 'loss_pct_mean', label: 'Loss %' },
  ],
  dns_latency: [
    { value: 'latency_ms_mean', label: 'Latency Mean' },
    { value: 'latency_ms_p95', label: 'Latency p95' },
    { value: 'latency_ms_p99', label: 'Latency p99' },
  ],
  http_timing: [
    { value: 'total_ms_mean', label: 'Total Mean' },
    { value: 'total_ms_p95', label: 'Total p95' },
    { value: 'total_ms_p99', label: 'Total p99' },
    { value: 'ttfb_ms_mean', label: 'TTFB Mean' },
  ],
  device_health: [
    { value: 'cpu_percent_mean', label: 'CPU %' },
    { value: 'memory_percent_mean', label: 'Memory %' },
    { value: 'cpu_percent_max', label: 'CPU Max %' },
  ],
}

const RANGES: TimeRange[] = ['15m', '1h', '6h', '24h', '7d']

export default function TimeSeriesChart() {
  const [measurement, setMeasurement] = useState('internet_rtt')
  const [field, setField] = useState('rtt_avg_ms_mean')
  const [range, setRange] = useState<TimeRange>('1h')

  const { data, loading, error } = useSeries(measurement, field, range)

  const currentFields = FIELDS[measurement] ?? []

  const option = useMemo(() => {
    const points = data?.points ?? []
    return {
      grid: { top: 30, right: 20, bottom: 30, left: 55 },
      xAxis: {
        type: 'category' as const,
        data: points.map((p) => {
          const d = new Date(p.time)
          return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }),
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#64748b', fontSize: 11 },
      },
      yAxis: {
        type: 'value' as const,
        splitLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#64748b', fontSize: 11 },
      },
      tooltip: {
        trigger: 'axis' as const,
        backgroundColor: '#1e293b',
        borderColor: '#334155',
        textStyle: { color: '#f1f5f9', fontSize: 12 },
      },
      series: [
        {
          type: 'line' as const,
          data: points.map((p) => p.value),
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#22d3ee', width: 2 },
          areaStyle: {
            color: {
              type: 'linear' as const,
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: '#22d3ee20' },
                { offset: 1, color: '#22d3ee02' },
              ],
            },
          },
        },
      ],
    }
  }, [data])

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <h3 className="text-sm font-medium text-slate-300 mr-auto">Network Performance</h3>

        <select
          value={measurement}
          onChange={(e) => {
            setMeasurement(e.target.value)
            const first = FIELDS[e.target.value]?.[0]
            if (first) setField(first.value)
          }}
          className="bg-slate-800 border border-slate-700 text-slate-300 text-xs rounded-lg px-2 py-1.5 focus:ring-cyan-400 focus:border-cyan-400"
        >
          {MEASUREMENTS.map((m) => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>

        <select
          value={field}
          onChange={(e) => setField(e.target.value)}
          className="bg-slate-800 border border-slate-700 text-slate-300 text-xs rounded-lg px-2 py-1.5 focus:ring-cyan-400 focus:border-cyan-400"
        >
          {currentFields.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>

        <div className="flex rounded-lg border border-slate-700 overflow-hidden">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-2.5 py-1 text-xs font-medium transition-colors ${
                range === r
                  ? 'bg-cyan-400/20 text-cyan-400'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      {error ? (
        <div className="h-[250px] flex items-center justify-center text-sm text-red-400">
          {error}
        </div>
      ) : loading && !data ? (
        <div className="h-[250px] flex items-center justify-center text-sm text-slate-500">
          Loading...
        </div>
      ) : (
        <ReactECharts
          option={option}
          style={{ height: 250, width: '100%' }}
          opts={{ renderer: 'svg' }}
          notMerge
        />
      )}
    </div>
  )
}
