/** BXI score → Tailwind color class mappings for rendering. */

const COLOR_MAP: Record<string, { text: string; bg: string; ring: string; hex: string }> = {
  emerald: { text: 'text-emerald-400', bg: 'bg-emerald-400', ring: 'ring-emerald-400', hex: '#34d399' },
  cyan:    { text: 'text-cyan-400',    bg: 'bg-cyan-400',    ring: 'ring-cyan-400',    hex: '#22d3ee' },
  amber:   { text: 'text-amber-400',   bg: 'bg-amber-400',   ring: 'ring-amber-400',   hex: '#fbbf24' },
  orange:  { text: 'text-orange-400',  bg: 'bg-orange-400',  ring: 'ring-orange-400',  hex: '#fb923c' },
  red:     { text: 'text-red-400',     bg: 'bg-red-400',     ring: 'ring-red-400',     hex: '#f87171' },
}

export function bxiColors(color: string) {
  return COLOR_MAP[color] ?? COLOR_MAP['cyan']!
}

/** Gauge color stops for ECharts (0-1 range). */
export const GAUGE_COLOR_STOPS: [number, string][] = [
  [0.29, '#f87171'],   // red
  [0.49, '#fb923c'],   // orange
  [0.69, '#fbbf24'],   // amber
  [0.89, '#22d3ee'],   // cyan
  [1.0,  '#34d399'],   // emerald
]
