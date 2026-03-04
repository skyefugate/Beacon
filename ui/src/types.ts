/** TypeScript interfaces mirroring the backend API responses. */

export interface BXIData {
  score: number
  label: string
  color: string
  components: Record<string, number>
}

export interface MetricFields {
  [field: string]: number | string | null
}

export interface EscalationData {
  state: string
  since: string | null
}

export interface AgentInfo {
  probe_id: string
  version: string
  uptime_seconds: number
}

export interface ContextData {
  hostname?: string
  os?: string
  os_version?: string
  arch?: string
  system_uptime_hours?: number
  primary_interface?: string
  interface_speed_mbps?: number
  interface_mtu?: number
  mac_address?: string
  link_type?: string
  default_gateway?: string
  dns_servers?: string
  public_ip?: string
  vpn_active?: boolean
  asn?: string
  isp_name?: string
  geo_city?: string
  geo_region?: string
  geo_country?: string
}

export interface OverviewResponse {
  bxi: BXIData
  metrics: Record<string, MetricFields>
  context: ContextData
  escalation: EscalationData
  agent: AgentInfo
}

export interface TimePoint {
  time: string
  value: number | null
}

export interface SeriesResponse {
  measurement: string
  field: string
  range: string
  points: TimePoint[]
}

export interface SparklinesResponse {
  range: string
  window_seconds: number
  sparklines: Record<string, TimePoint[]>
}

export type TimeRange = '5m' | '15m' | '1h' | '6h' | '24h' | '7d'
