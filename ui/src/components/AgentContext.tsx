import type { ContextData } from '../types'

interface AgentContextProps {
  context: ContextData
}

function Row({ label, value }: { label: string; value?: string | number | boolean | null }) {
  if (value == null || value === '') return null
  const display = typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value)
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-300 font-mono truncate max-w-[60%] text-right">{display}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-[10px] uppercase tracking-wider text-slate-600 mb-1.5">{title}</h4>
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  )
}

export default function AgentContext({ context }: AgentContextProps) {
  const hasDevice = context.hostname || context.os
  const hasNetwork = context.primary_interface || context.default_gateway || context.dns_servers
  const hasGeo = context.isp_name || context.geo_city || context.geo_country

  if (!hasDevice && !hasNetwork && !hasGeo) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <h3 className="text-sm font-medium text-slate-300 mb-3">Agent Context</h3>
        <p className="text-xs text-slate-600">Waiting for context data...</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h3 className="text-sm font-medium text-slate-300 mb-3">Agent Context</h3>
      <div className="flex flex-col gap-3">
        {hasDevice && (
          <Section title="Device">
            <Row label="Host" value={context.hostname} />
            <Row label="OS" value={context.os && context.os_version ? `${context.os} ${context.os_version}` : context.os} />
            <Row label="Arch" value={context.arch} />
            <Row label="Uptime" value={context.system_uptime_hours != null ? `${context.system_uptime_hours}h` : undefined} />
          </Section>
        )}

        {hasNetwork && (
          <Section title="Network">
            <Row label="Interface" value={context.primary_interface} />
            <Row label="Link" value={context.link_type} />
            {context.interface_speed_mbps != null && context.interface_speed_mbps > 0 && (
              <Row label="Speed" value={`${context.interface_speed_mbps} Mbps`} />
            )}
            <Row label="Gateway" value={context.default_gateway} />
            <Row label="DNS" value={context.dns_servers} />
            <Row label="Public IP" value={context.public_ip} />
            <Row label="VPN" value={context.vpn_active} />
          </Section>
        )}

        {hasGeo && (
          <Section title="Location">
            <Row label="ISP" value={context.isp_name} />
            <Row label="ASN" value={context.asn} />
            <Row
              label="Location"
              value={[context.geo_city, context.geo_region, context.geo_country].filter(Boolean).join(', ') || undefined}
            />
          </Section>
        )}
      </div>
    </div>
  )
}
