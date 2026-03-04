import AgentContext from '../components/AgentContext'
import BXIGauge from '../components/BXIGauge'
import EscalationBadge from '../components/EscalationBadge'
import EventTimeline from '../components/EventTimeline'
import Footer from '../components/Footer'
import Header from '../components/Header'
import MetricGrid from '../components/MetricGrid'
import SystemHealth from '../components/SystemHealth'
import TimeSeriesChart from '../components/TimeSeriesChart'
import { useOverview, useSparklines } from '../hooks/useOverview'

export default function Dashboard() {
  const { data: overview, error: overviewError, loading: overviewLoading, lastUpdated } = useOverview()
  const { data: sparklines } = useSparklines()

  const isOnline = !overviewError && !!overview
  const dataFresh = lastUpdated ? (Date.now() - lastUpdated.getTime()) < 30_000 : false

  // Loading state
  if (overviewLoading && !overview) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <div className="inline-block h-8 w-8 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent" />
          <p className="mt-3 text-sm text-slate-400">Connecting to Beacon...</p>
        </div>
      </div>
    )
  }

  // Error state (no data at all)
  if (!overview) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center max-w-md">
          <div className="text-4xl mb-3">!</div>
          <h2 className="text-lg font-semibold text-slate-200 mb-2">Unable to Connect</h2>
          <p className="text-sm text-slate-400 mb-4">
            {overviewError ?? 'Could not reach the Beacon API. Make sure the server is running.'}
          </p>
          <p className="text-xs text-slate-600">
            The dashboard will automatically retry every 10 seconds.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col min-h-screen">
      <Header probeId={overview.agent.probe_id} isOnline={isOnline && dataFresh} />

      <main className="flex-1 p-6 max-w-7xl mx-auto w-full">
        <div className="flex flex-col gap-6">

          {/* Top row: BXI gauge + metric cards */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px_1fr]">
            <div className="flex flex-col gap-3">
              <BXIGauge bxi={overview.bxi} />
              <EscalationBadge escalation={overview.escalation} />
            </div>
            <MetricGrid metrics={overview.metrics} sparklines={sparklines} />
          </div>

          {/* Time series chart */}
          <TimeSeriesChart />

          {/* Bottom row: Event timeline + System health + Agent context */}
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            <EventTimeline metrics={overview.metrics} />
            <SystemHealth
              device={overview.metrics['device_health'] ?? {}}
              agent={overview.agent}
            />
            <AgentContext context={overview.context ?? {}} />
          </div>
        </div>
      </main>

      <Footer
        probeId={overview.agent.probe_id}
        version={overview.agent.version}
        lastUpdated={lastUpdated}
      />
    </div>
  )
}
