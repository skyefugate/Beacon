import { formatNumber, trendDirection } from '../lib/format'
import type { TimePoint } from '../types'
import SparkLine from './SparkLine'

interface MetricCardProps {
  label: string
  value: number | null
  unit: string
  p95?: number | null
  sparkData: TimePoint[]
  /** If true, 'up' is bad (e.g., latency). If false, 'up' is neutral (e.g., cpu). */
  lowerIsBetter?: boolean
}

function TrendArrow({ direction, lowerIsBetter }: { direction: 'up' | 'down' | 'flat'; lowerIsBetter: boolean }) {
  if (direction === 'flat') return <span className="text-slate-500">--</span>

  const isGood = lowerIsBetter ? direction === 'down' : direction === 'up'
  const color = isGood ? 'text-emerald-400' : 'text-red-400'
  const arrow = direction === 'up' ? '\u2191' : '\u2193'

  return <span className={color}>{arrow}</span>
}

export default function MetricCard({
  label,
  value,
  unit,
  p95,
  sparkData,
  lowerIsBetter = true,
}: MetricCardProps) {
  const trend = trendDirection(sparkData.map((p) => p.value))

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-400">{label}</span>
        <TrendArrow direction={trend} lowerIsBetter={lowerIsBetter} />
      </div>

      <div className="flex items-baseline gap-1.5">
        <span className="text-2xl font-semibold text-slate-100">
          {formatNumber(value)}
        </span>
        <span className="text-sm text-slate-500">{unit}</span>
      </div>

      {p95 != null && (
        <div className="text-xs text-slate-500">
          p95: {formatNumber(p95)} {unit}
        </div>
      )}

      <SparkLine points={sparkData} />
    </div>
  )
}
