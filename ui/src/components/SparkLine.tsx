import ReactECharts from 'echarts-for-react'
import { useMemo } from 'react'
import type { TimePoint } from '../types'

interface SparkLineProps {
  points: TimePoint[]
  color?: string
  height?: number
}

export default function SparkLine({ points, color = '#22d3ee', height = 40 }: SparkLineProps) {
  const option = useMemo(() => ({
    grid: { top: 2, right: 2, bottom: 2, left: 2 },
    xAxis: { type: 'category' as const, show: false, data: points.map((p) => p.time) },
    yAxis: { type: 'value' as const, show: false },
    series: [
      {
        type: 'line' as const,
        data: points.map((p) => p.value),
        smooth: true,
        symbol: 'none',
        lineStyle: { color, width: 1.5 },
        areaStyle: {
          color: {
            type: 'linear' as const,
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: color + '40' },
              { offset: 1, color: color + '05' },
            ],
          },
        },
      },
    ],
    tooltip: { show: false },
  }), [points, color])

  if (points.length === 0) {
    return <div style={{ height }} className="flex items-center justify-center text-slate-600 text-xs">No data</div>
  }

  return (
    <ReactECharts
      option={option}
      style={{ height, width: '100%' }}
      opts={{ renderer: 'svg' }}
      notMerge
    />
  )
}
