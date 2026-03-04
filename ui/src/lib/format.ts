/** Formatting utilities for the dashboard. */

/** Format a number with appropriate precision. */
export function formatNumber(value: number | null | undefined, decimals = 1): string {
  if (value == null) return '--'
  return value.toFixed(decimals)
}

/** Format milliseconds as a human-readable duration. */
export function formatDuration(ms: number): string {
  if (ms < 1) return '<1ms'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

/** Format seconds as uptime (e.g., "2h 15m"). */
export function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60) % 60
  const h = Math.floor(seconds / 3600) % 24
  const d = Math.floor(seconds / 86400)
  const parts: string[] = []
  if (d > 0) parts.push(`${d}d`)
  if (h > 0) parts.push(`${h}h`)
  if (m > 0) parts.push(`${m}m`)
  return parts.join(' ') || '0m'
}

/** Format a Date as relative time (e.g., "5s ago"). */
export function formatRelativeTime(date: Date | null): string {
  if (!date) return 'never'
  const diff = Math.floor((Date.now() - date.getTime()) / 1000)
  if (diff < 5) return 'just now'
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

/** Determine trend direction from a sparkline series. */
export function trendDirection(
  values: (number | null)[],
): 'up' | 'down' | 'flat' {
  const nums = values.filter((v): v is number => v != null)
  if (nums.length < 2) return 'flat'
  const recent = nums.slice(-5)
  const older = nums.slice(0, 5)
  const recentAvg = recent.reduce((a, b) => a + b, 0) / recent.length
  const olderAvg = older.reduce((a, b) => a + b, 0) / older.length
  const diff = recentAvg - olderAvg
  const threshold = olderAvg * 0.05 // 5% change threshold
  if (diff > threshold) return 'up'
  if (diff < -threshold) return 'down'
  return 'flat'
}
