import { useCallback, useEffect, useRef, useState } from 'react'

interface PollingResult<T> {
  data: T | null
  error: string | null
  loading: boolean
  lastUpdated: Date | null
}

/**
 * Generic polling hook. Calls `fetcher` immediately and then every
 * `intervalMs` milliseconds. Re-fetches when `deps` change.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  deps: unknown[] = [],
): PollingResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const mountedRef = useRef(true)

  const doFetch = useCallback(async () => {
    try {
      const result = await fetcher()
      if (mountedRef.current) {
        setData(result)
        setError(null)
        setLastUpdated(new Date())
      }
    } catch (e) {
      if (mountedRef.current) {
        setError(e instanceof Error ? e.message : 'Unknown error')
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    mountedRef.current = true
    setLoading(true)
    doFetch()

    const id = setInterval(doFetch, intervalMs)
    return () => {
      mountedRef.current = false
      clearInterval(id)
    }
  }, [doFetch, intervalMs])

  return { data, error, loading, lastUpdated }
}
