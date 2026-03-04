import { fetchOverview, fetchSparklines } from '../api/client'
import type { OverviewResponse, SparklinesResponse } from '../types'
import { usePolling } from './usePolling'

/** Polls the overview endpoint every 10 seconds. */
export function useOverview() {
  return usePolling<OverviewResponse>(fetchOverview, 10_000)
}

/** Polls sparklines every 10 seconds. */
export function useSparklines() {
  return usePolling<SparklinesResponse>(() => fetchSparklines('1h'), 10_000)
}
