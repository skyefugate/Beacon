import type { OverviewResponse, SeriesResponse, SparklinesResponse, TimeRange } from '../types'

const BASE = '/api/telemetry'

async function fetchJSON<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) {
    throw new Error(`API ${resp.status}: ${resp.statusText}`)
  }
  return resp.json() as Promise<T>
}

export function fetchOverview(): Promise<OverviewResponse> {
  return fetchJSON<OverviewResponse>(`${BASE}/overview`)
}

export function fetchSeries(
  measurement: string,
  field: string,
  range: TimeRange,
): Promise<SeriesResponse> {
  const params = new URLSearchParams({ measurement, field, range })
  return fetchJSON<SeriesResponse>(`${BASE}/series?${params}`)
}

export function fetchSparklines(range: TimeRange = '1h'): Promise<SparklinesResponse> {
  const params = new URLSearchParams({ range })
  return fetchJSON<SparklinesResponse>(`${BASE}/sparklines?${params}`)
}
