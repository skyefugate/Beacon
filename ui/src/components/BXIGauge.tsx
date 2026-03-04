import ReactECharts from 'echarts-for-react'
import { useMemo } from 'react'
import { bxiColors, GAUGE_COLOR_STOPS } from '../lib/bxi'
import type { BXIData } from '../types'

interface BXIGaugeProps {
  bxi: BXIData
}

export default function BXIGauge({ bxi }: BXIGaugeProps) {
  const colors = bxiColors(bxi.color)

  const option = useMemo(
    () => ({
      series: [
        {
          type: 'gauge' as const,
          startAngle: 225,
          endAngle: -45,
          min: 0,
          max: 100,
          pointer: { show: false },
          progress: {
            show: true,
            overlap: false,
            roundCap: true,
            width: 12,
            itemStyle: { color: colors.hex },
          },
          axisLine: {
            lineStyle: {
              width: 12,
              color: GAUGE_COLOR_STOPS,
              opacity: 0.15,
            },
          },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          detail: {
            fontSize: 42,
            fontWeight: 700,
            fontFamily: 'Inter, system-ui',
            color: colors.hex,
            offsetCenter: [0, '-10%'],
            formatter: '{value}',
          },
          title: {
            fontSize: 14,
            fontFamily: 'Inter, system-ui',
            color: '#94a3b8',
            offsetCenter: [0, '25%'],
          },
          data: [{ value: bxi.score, name: bxi.label }],
          animationDuration: 800,
          animationEasingUpdate: 'cubicOut' as const,
        },
      ],
    }),
    [bxi.score, bxi.label, colors.hex],
  )

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 flex flex-col items-center">
      <ReactECharts
        option={option}
        style={{ height: 200, width: '100%' }}
        opts={{ renderer: 'svg' }}
        notMerge
      />
    </div>
  )
}
