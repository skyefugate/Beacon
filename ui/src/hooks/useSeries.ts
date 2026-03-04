import { fetchSeries } from '../api/client'
import type { SeriesResponse, TimeRange } from '../types'
import { usePolling } from './usePolling'

/** Polls a time series endpoint every 30 seconds. Re-fetches on param changes. */
export function useSeries(measurement: string, field: string, range: TimeRange) {
  return usePolling<SeriesResponse>(
    () => fetchSeries(measurement, field, range),
    30_000,
    [measurement, field, range],
  )
}
