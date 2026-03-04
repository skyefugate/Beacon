# Beacon Telemetry Mode v2: Deep Observability Design

**Status**: Design
**Schema Version**: 2.0 (telemetry extends 1.1 evidence schema)
**Author**: Beacon Architecture
**Date**: 2026-02-11

---

## Overview

Packs are point-in-time snapshots: "take a picture of the network right now."
Telemetry is a continuous stream: "watch the network and tell me when it hurts."

The two share the same plugin system and PluginEnvelope contract but have
fundamentally different execution models. Packs are imperative (run all steps,
build evidence, done). Telemetry is reactive (sample continuously, aggregate
into windows, escalate on anomaly, de-escalate when stable).

### Design Principles

1. **The probe must never be the problem.** If Beacon causes the degradation
   it's trying to detect, it has failed. Resource guardrails are not optional.
2. **Causal signals over vanity metrics.** "RSSI is -72" is a number. "RSSI
   dropped 15 dB in 20 seconds while the user roamed from AP-lobby to AP-3F
   and DNS p95 spiked from 8ms to 400ms" is a diagnosis.
3. **Privacy by default.** SSIDs and BSSIDs are hashed. IP addresses are
   tagged by role (gateway, resolver, target), not stored raw. Opt-in for
   plaintext identifiers.
4. **Window aggregation, not raw floods.** Store percentiles (p50/p95/p99)
   over 60-second windows, not every individual sample. This is what makes
   always-on telemetry sustainable.

---

## SECTION 1 — Telemetry Tiers

### Tier 0: Baseline (Always-On)

**Goal**: Continuous heartbeat. Detect degradation within 60 seconds. No sudo.
**CPU**: <1% sustained
**Data rate**: ~2 KB/min

| Measurement | Fields (units) | Tags | Sample Interval | Window |
|---|---|---|---|---|
| `t_wifi_link` | `rssi_dbm`, `noise_dbm`, `snr_db`, `tx_rate_mbps`, `mcs_index` | `interface`, `channel`, `phy_mode`, `band`, `ssid_hash`, `bssid_hash`, `method` | 30s | 60s |
| `t_gateway_rtt` | `rtt_p50_ms`, `rtt_p95_ms`, `rtt_p99_ms`, `rtt_min_ms`, `rtt_max_ms`, `loss_pct`, `jitter_ms`, `probes` | `gateway`, `interface` | 10s (3 probes) | 60s |
| `t_internet_rtt` | `rtt_p50_ms`, `rtt_p95_ms`, `rtt_p99_ms`, `rtt_min_ms`, `rtt_max_ms`, `loss_pct`, `jitter_ms`, `probes` | `target`, `target_name` | 10s (3 probes) | 60s |
| `t_dns_latency` | `latency_p50_ms`, `latency_p95_ms`, `latency_p99_ms`, `success_rate`, `timeout_count`, `samples` | `resolver`, `domain` | 30s | 60s |
| `t_http_timing` | `dns_ms`, `connect_ms`, `tls_ms`, `ttfb_ms`, `total_ms`, `status_code`, `success` | `target`, `method` | 60s | 60s |
| `t_device_health` | `cpu_pct`, `mem_pct`, `load_1m` | — | 30s | 60s |

**Tier 0 Events** (emitted on change, not periodically):

| Event Type | Trigger | Severity |
|---|---|---|
| `route_change` | Default gateway IP or interface changed | WARNING |
| `dns_server_change` | System resolver list changed | INFO |
| `ip_change` | Primary interface IPv4/IPv6 changed | INFO |
| `ssid_change` | Connected SSID hash changed | INFO |
| `link_state_change` | Primary interface went up/down | CRITICAL |

### Tier 1: Enhanced Wi-Fi & Network Context

**Goal**: Deeper radio and transport visibility. Requires either privileged
sidecar or periodic sudo elevation.
**CPU**: <3% sustained
**Data rate**: ~8 KB/min (additive to Tier 0)

| Measurement | Fields (units) | Tags | Sample Interval | Window |
|---|---|---|---|---|
| `t_wifi_quality` | `retry_pct`, `tx_failures`, `rx_errors`, `rate_shift_count`, `beacon_loss_count` | `interface`, `bssid_hash` | 15s | 60s |
| `t_wifi_roam` | `prev_bssid_hash`, `new_bssid_hash`, `prev_channel`, `new_channel`, `rssi_before`, `rssi_after`, `roam_time_ms`, `reason_code` | `interface`, `ssid_hash` | event | — |
| `t_wifi_channel` | `utilization_pct`, `airtime_busy_pct`, `noise_floor_dbm`, `station_count` | `interface`, `channel`, `band` | 30s | 60s |
| `t_wifi_deauth` | `reason_code`, `source_bssid_hash`, `locally_generated` | `interface` | event | — |
| `t_vpn_tunnel` | `detected`, `type`, `mtu`, `overhead_ms`, `inner_ip_hash` | `tunnel_interface`, `provider` | 60s | — |
| `t_tls_timing` | `handshake_ms`, `protocol_version`, `cipher_suite`, `cert_days_remaining` | `target`, `sni` | 60s | 60s |

**Tier 1 Events**:

| Event Type | Trigger | Severity |
|---|---|---|
| `wifi_roam` | BSSID changed | INFO |
| `wifi_deauth` | Deauth/disassoc frame received | WARNING |
| `channel_switch` | Channel or bandwidth changed | INFO |
| `vpn_mtu_change` | VPN tunnel MTU changed | WARNING |

### Tier 2: Experience & Stress Probes

**Goal**: Active experience measurement. Generates load. Scheduled or
anomaly-triggered. Never runs continuously.
**CPU**: 10-20% during window (60-120s max)
**Data rate**: ~50 KB per test window

| Measurement | Fields (units) | Tags | Trigger | Duration |
|---|---|---|---|---|
| `t_bufferbloat` | `idle_rtt_ms`, `loaded_rtt_ms`, `bloat_ms`, `download_mbps`, `upload_mbps`, `responsiveness_rpm` | `target`, `method` | scheduled / anomaly | 15-30s |
| `t_saas_probe` | `dns_ms`, `connect_ms`, `tls_ms`, `ttfb_ms`, `total_ms`, `status_code`, `redirect_count` | `service`, `endpoint`, `region` | scheduled | per-request |
| `t_route_snapshot` | `hop_count`, `timeout_hops`, `new_hops`, `lost_hops`, `path_hash` | `target` | 5min / anomaly | 10-30s |
| `t_burst_sample` | (same fields as Tier 0 measurements but at 1s interval) | `tier=burst` | anomaly | 60-120s |

**Tier 2 never runs without a reason**: either a schedule or an escalation trigger.

---

## SECTION 2 — Event-Driven Escalation

### Escalation State Machine

```
                    ┌─────────────┐
                    │   BASELINE  │  Tier 0 only
                    │  (steady)   │
                    └──────┬──────┘
                           │ trigger fires
                           ▼
                    ┌─────────────┐
                    │  ELEVATED   │  Tier 0 + Tier 1
                    │ (enhanced)  │  + increased T0 frequency
                    └──────┬──────┘
                           │ trigger persists
                           │ or secondary trigger
                           ▼
                    ┌─────────────┐
                    │   ACTIVE    │  Tier 0 + 1 + Tier 2 window
                    │  (probing)  │  + burst sampling
                    └──────┬──────┘
                           │ window expires
                           ▼
                    ┌─────────────┐
                    │  COOLDOWN   │  Back to Tier 0 + 1
                    │ (30-60s)    │  no re-escalation
                    └──────┬──────┘
                           │ cooldown expires
                           │ + metrics stable
                           ▼
                    ┌─────────────┐
                    │   BASELINE  │
                    └─────────────┘
```

**Flap guard**: After de-escalation, a cooldown period (default 60s) prevents
immediate re-triggering. If the same trigger fires 3+ times in 10 minutes,
the escalation window extends but does NOT re-run Tier 2 stress probes
(to avoid becoming the problem).

### Trigger Rules

```yaml
triggers:
  rssi_drop:
    condition: "delta(t_wifi_link.rssi_dbm, 30s) < -10"
    description: "RSSI dropped >10 dB in 30 seconds"
    escalate_to: elevated
    cooldown_seconds: 60

  roam_storm:
    condition: "count(wifi_roam, 5m) >= 3"
    description: "3+ roams in 5 minutes"
    escalate_to: active
    cooldown_seconds: 120

  sustained_loss:
    condition: "avg(t_internet_rtt.loss_pct, 60s) > 3"
    description: "Packet loss >3% sustained for 60 seconds"
    escalate_to: elevated
    cooldown_seconds: 60

  dns_latency_spike:
    condition: "t_dns_latency.latency_p95_ms > 200"
    description: "DNS p95 latency exceeds 200ms"
    escalate_to: elevated
    cooldown_seconds: 60

  route_change:
    condition: "event(route_change)"
    description: "Default route changed"
    escalate_to: active
    cooldown_seconds: 30

  http_ttfb_spike:
    condition: "t_http_timing.ttfb_ms > 2000"
    description: "HTTP TTFB exceeds 2 seconds"
    escalate_to: elevated
    cooldown_seconds: 60

  gateway_unreachable:
    condition: "t_gateway_rtt.loss_pct >= 100"
    description: "Gateway completely unreachable"
    escalate_to: active
    cooldown_seconds: 30

  jitter_spike:
    condition: "t_internet_rtt.jitter_ms > 50"
    description: "Internet jitter exceeds 50ms"
    escalate_to: elevated
    cooldown_seconds: 60
```

### Escalation Actions

| Transition | Actions |
|---|---|
| BASELINE → ELEVATED | Enable Tier 1 collectors, increase Tier 0 gateway/internet ping to 5s interval, emit `anomaly_trigger` event |
| ELEVATED → ACTIVE | Run traceroute burst, start 1s burst sampling window (120s max), optionally auto-generate diagnostic pack, emit `escalation_active` event |
| ACTIVE → COOLDOWN | Stop burst sampling, stop Tier 2 probes, keep Tier 1 running, emit `escalation_cooldown` event |
| COOLDOWN → BASELINE | Disable Tier 1 (if not configured always-on), restore normal intervals, emit `escalation_resolved` event |

### Auto-Pack Generation

When escalation reaches ACTIVE state, the telemetry engine can optionally
trigger a full diagnostic pack run (same as `beacon run full_diagnostic`).
This produces a self-contained evidence pack tied to the anomaly window:

```
anomaly detected → burst sampling starts → pack auto-triggered
                                         → evidence pack saved with
                                           anomaly_trigger_ref linking
                                           to the telemetry window
```

---

## SECTION 3 — Data Model

### Streaming Telemetry Point

Every telemetry data point follows this structure, compatible with InfluxDB
line protocol, Prometheus exposition format, and OTLP metrics:

```
┌──────────────────────────────────────────────────────────────┐
│ TelemetryPoint                                               │
├──────────────────────────────────────────────────────────────┤
│ measurement : str           "t_wifi_link"                    │
│ timestamp   : datetime      2026-02-11T14:30:00.000Z         │
│ tags        : dict[str,str]                                  │
│   host_id   : "beacon-01"                                    │
│   probe_id  : "probe-hq-3f"                                 │
│   interface : "en0"                                          │
│   tier      : "0"                                            │
│   ssid_hash : "a1b2c3d4"   (SHA-256 truncated to 8 chars)   │
│   bssid_hash: "e5f6g7h8"                                    │
│ fields      : dict[str, float|int|str|bool]                  │
│   rssi_dbm  : -52                                            │
│   noise_dbm : -90                                            │
│   snr_db    : 38                                             │
│   tx_rate   : 864                                            │
│ window      : WindowMeta (optional)                          │
│   start     : datetime                                       │
│   end       : datetime                                       │
│   samples   : int                                            │
│ event_type  : str | None    (for discrete events only)       │
└──────────────────────────────────────────────────────────────┘
```

### Privacy Modes

```yaml
privacy:
  mode: "hashed"  # "hashed" | "redacted" | "plaintext"

  # hashed (default):
  #   SSID "CorpNet-5G" → SHA-256 truncated → "a1b2c3d4"
  #   BSSID "AA:BB:CC:DD:EE:FF" → "e5f6a7b8"
  #   Consistent hashing: same SSID always maps to same hash
  #   Allows correlation without revealing names

  # redacted:
  #   SSID → "[redacted]"
  #   BSSID → "[redacted]"
  #   No correlation possible, maximum privacy

  # plaintext:
  #   SSID → "CorpNet-5G"
  #   BSSID → "AA:BB:CC:DD:EE:FF"
  #   Opt-in only, requires explicit configuration

  hash_salt: ""  # Optional salt for HMAC-SHA256 (empty = plain SHA-256)

  # IP address handling (all modes):
  #   Gateway IP → tagged as role=gateway, stored as-is (RFC1918, not PII)
  #   Public IP → stored only in evidence packs, not in telemetry stream
  #   DNS resolver IPs → stored as-is (infrastructure, not PII)
```

### Capability Matrix

What each tier can collect on macOS, with and without privilege:

| Capability | macOS (no sudo) | macOS (sudo / sidecar) | Linux (no sudo) | Linux (sudo / sidecar) |
|---|---|---|---|---|
| RSSI / Noise / SNR | system_profiler (30s+) | wdutil (fast) | — | iw link |
| Channel / PHY / MCS | system_profiler | wdutil / airport | — | iw link |
| TX Rate | system_profiler | wdutil | — | iw link |
| Retry / TX Failures | — | wdutil dump (if available) | — | iw station dump |
| BSSID Tracking | system_profiler | wdutil | — | iw link |
| Channel Utilization | — | wdutil dump | — | iw survey dump |
| Deauth / Disassoc | — | pcap on en0 (BPF) | — | iw event |
| Gateway Ping | ICMP (unprivileged on macOS) | raw ICMP | ping command | raw ICMP |
| Traceroute | UDP traceroute | raw ICMP traceroute | UDP traceroute | raw ICMP traceroute |
| VPN Detection | route table + utun check | same | route table + tun check | same |
| networkQuality | `networkQuality -s` (built-in) | same | — (use iperf3) | same |
| TLS Timing | httpx (Python) | same | same | same |
| Route Table | `netstat -rn` | same | `ip route` | same |

### Example Telemetry Events (JSON)

**wifi_link_sample** (Tier 0, windowed):
```json
{
  "measurement": "t_wifi_link",
  "timestamp": "2026-02-11T14:30:00Z",
  "tags": {
    "host_id": "beacon-01",
    "probe_id": "probe-hq-3f",
    "interface": "en0",
    "tier": "0",
    "band": "5GHz",
    "channel": "149",
    "phy_mode": "802.11ax",
    "ssid_hash": "a1b2c3d4",
    "bssid_hash": "e5f6a7b8",
    "method": "system_profiler"
  },
  "fields": {
    "rssi_dbm": -52,
    "noise_dbm": -90,
    "snr_db": 38,
    "tx_rate_mbps": 864,
    "mcs_index": 8
  },
  "window": {
    "start": "2026-02-11T14:29:00Z",
    "end": "2026-02-11T14:30:00Z",
    "samples": 2
  }
}
```

**roam_event** (Tier 1, discrete):
```json
{
  "measurement": "t_wifi_roam",
  "timestamp": "2026-02-11T14:30:12Z",
  "tags": {
    "host_id": "beacon-01",
    "interface": "en0",
    "tier": "1",
    "ssid_hash": "a1b2c3d4"
  },
  "fields": {
    "prev_bssid_hash": "e5f6a7b8",
    "new_bssid_hash": "f7g8h9i0",
    "prev_channel": "149",
    "new_channel": "36",
    "rssi_before": -72,
    "rssi_after": -55,
    "roam_time_ms": 180
  },
  "event_type": "wifi_roam"
}
```

**ping_window** (Tier 0, aggregated):
```json
{
  "measurement": "t_internet_rtt",
  "timestamp": "2026-02-11T14:30:00Z",
  "tags": {
    "host_id": "beacon-01",
    "tier": "0",
    "target": "8.8.8.8",
    "target_name": "google_dns"
  },
  "fields": {
    "rtt_p50_ms": 15.2,
    "rtt_p95_ms": 22.8,
    "rtt_p99_ms": 45.1,
    "rtt_min_ms": 12.0,
    "rtt_max_ms": 48.3,
    "loss_pct": 0.0,
    "jitter_ms": 3.4,
    "probes": 18
  },
  "window": {
    "start": "2026-02-11T14:29:00Z",
    "end": "2026-02-11T14:30:00Z",
    "samples": 6
  }
}
```

**dns_window** (Tier 0, aggregated):
```json
{
  "measurement": "t_dns_latency",
  "timestamp": "2026-02-11T14:30:00Z",
  "tags": {
    "host_id": "beacon-01",
    "tier": "0",
    "resolver": "8.8.8.8",
    "domain": "google.com"
  },
  "fields": {
    "latency_p50_ms": 5.2,
    "latency_p95_ms": 8.1,
    "latency_p99_ms": 12.3,
    "success_rate": 1.0,
    "timeout_count": 0,
    "samples": 2
  },
  "window": {
    "start": "2026-02-11T14:29:00Z",
    "end": "2026-02-11T14:30:00Z",
    "samples": 2
  }
}
```

**http_timing** (Tier 0, per-request):
```json
{
  "measurement": "t_http_timing",
  "timestamp": "2026-02-11T14:30:00Z",
  "tags": {
    "host_id": "beacon-01",
    "tier": "0",
    "target": "https://www.google.com",
    "method": "HEAD"
  },
  "fields": {
    "dns_ms": 4.2,
    "connect_ms": 12.1,
    "tls_ms": 28.5,
    "ttfb_ms": 52.3,
    "total_ms": 55.8,
    "status_code": 200,
    "success": true
  }
}
```

**route_change_event** (Tier 0, discrete):
```json
{
  "measurement": "t_route_change",
  "timestamp": "2026-02-11T14:30:45Z",
  "tags": {
    "host_id": "beacon-01",
    "tier": "0",
    "interface": "en0"
  },
  "fields": {
    "prev_gateway": "192.168.1.1",
    "new_gateway": "10.0.0.1",
    "prev_interface": "en0",
    "new_interface": "utun3"
  },
  "event_type": "route_change"
}
```

**anomaly_trigger** (escalation event):
```json
{
  "measurement": "t_anomaly",
  "timestamp": "2026-02-11T14:30:12Z",
  "tags": {
    "host_id": "beacon-01",
    "tier": "0",
    "trigger_rule": "rssi_drop"
  },
  "fields": {
    "trigger_value": -15.0,
    "threshold": -10.0,
    "prev_state": "baseline",
    "new_state": "elevated",
    "description": "RSSI dropped 15 dB in 30 seconds"
  },
  "event_type": "anomaly_trigger"
}
```

---

## SECTION 4 — Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  BEACON TELEMETRY ENGINE                                            │
│                                                                     │
│  ┌──────────────────────────────────────────────────────┐          │
│  │  Telemetry Scheduler                                  │          │
│  │                                                       │          │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐       │          │
│  │  │ Tier 0   │  │ Tier 1   │  │ Tier 2       │       │          │
│  │  │ Samplers │  │ Samplers │  │ Probes       │       │          │
│  │  │ (always) │  │ (on esc) │  │ (on trigger) │       │          │
│  │  │ 10-60s   │  │ 15-60s   │  │ burst/sched  │       │          │
│  │  └────┬─────┘  └────┬─────┘  └──────┬───────┘       │          │
│  │       └──────────────┼───────────────┘               │          │
│  │                      ▼                                │          │
│  │           ┌─────────────────────┐                    │          │
│  │           │  Sample Collector   │                    │          │
│  │           │  (raw data points)  │                    │          │
│  │           └──────────┬──────────┘                    │          │
│  └──────────────────────┼───────────────────────────────┘          │
│                         ▼                                           │
│  ┌──────────────────────────────────────────────────────┐          │
│  │  Window Aggregator                                    │          │
│  │                                                       │          │
│  │  Raw samples → 60s windows → p50/p95/p99/min/max     │          │
│  │  Ring buffer per measurement (keep last 10 minutes)   │          │
│  │  Discrete events pass through unchanged               │          │
│  └──────────────────────┬───────────────────────────────┘          │
│                         │                                           │
│              ┌──────────┼──────────┐                               │
│              ▼                     ▼                                │
│  ┌────────────────────┐  ┌─────────────────────┐                  │
│  │  Anomaly Detector  │  │  Local Buffer        │                  │
│  │                     │  │                      │                  │
│  │  Trigger rules      │  │  SQLite WAL mode     │                  │
│  │  evaluated per      │  │  ~50MB default cap   │                  │
│  │  window cycle       │  │  7-day retention     │                  │
│  │                     │  │  Auto-compact        │                  │
│  └──────────┬─────────┘  └───────────┬──────────┘                  │
│             │                        │                              │
│             ▼                        ▼                              │
│  ┌────────────────────┐  ┌──────────────────────────┐             │
│  │  Escalation Mgr    │  │  Export Pipeline          │             │
│  │                     │  │                           │             │
│  │  State machine:     │  │  ┌─────────────────────┐ │             │
│  │  BASELINE           │  │  │ InfluxDB line proto  │ │             │
│  │  → ELEVATED         │  │  ├─────────────────────┤ │             │
│  │  → ACTIVE           │  │  │ Prometheus remote_   │ │             │
│  │  → COOLDOWN         │  │  │ write                │ │             │
│  │  → BASELINE         │  │  ├─────────────────────┤ │             │
│  │                     │  │  │ OTLP/gRPC metrics   │ │             │
│  │  Flap guard:        │  │  ├─────────────────────┤ │             │
│  │  60s cooldown       │  │  │ File (JSONL rotate) │ │             │
│  │  3x/10min → extend  │  │  └─────────────────────┘ │             │
│  └──────────┬─────────┘  └──────────────────────────┘             │
│             │                                                       │
│             ▼                                                       │
│  ┌────────────────────────────────────────────────┐                │
│  │  (optional) Auto-Pack Trigger                   │                │
│  │  Escalation → ACTIVE triggers full_diagnostic   │                │
│  │  Evidence pack linked to anomaly window          │                │
│  └─────────────────────────────────────────────────┘                │
│                                                                     │
│  ┌────────────────────────────────────────────────┐                │
│  │  Resource Governor                              │                │
│  │                                                 │                │
│  │  CPU: soft limit 5%, hard limit 10%             │                │
│  │  Memory: 100MB cap (buffer + aggregator)        │                │
│  │  Battery: reduce to Tier 0 only below 20%       │                │
│  │  Disk: buffer capped at 50MB, oldest evicted    │                │
│  │  Network: Tier 2 probes paused on metered conn  │                │
│  └─────────────────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────────────────┘

External:

┌──────────────────┐    ┌────────────────────┐    ┌──────────────┐
│  InfluxDB 2.x    │    │  Prometheus /       │    │  OTLP        │
│  (self-hosted)   │◄───│  Grafana Cloud      │◄───│  Collector   │
│                  │    │  (remote_write)     │    │  (gRPC)      │
└──────────────────┘    └────────────────────┘    └──────────────┘
```

### Host Collector vs Container Split

Wi-Fi telemetry **requires host access**. You cannot read RSSI from inside a
container without `network_mode: host` and capabilities. The architecture splits:

```
┌──────────────────────────────────────────────────────┐
│  HOST PROCESS: beacon-telemetry                       │
│  Runs as: user-level daemon (launchd / systemd)      │
│  Capabilities: none (Tier 0) or NET_ADMIN (Tier 0+1) │
│                                                       │
│  Responsibilities:                                    │
│  - All Wi-Fi sampling (system_profiler / wdutil / iw) │
│  - Gateway ping (ICMP)                                │
│  - Route/DNS/IP change detection                      │
│  - Window aggregation + anomaly detection             │
│  - Local SQLite buffer                                │
│  - Export to configured backends                      │
│                                                       │
│  NOT in a container because:                          │
│  - Wi-Fi metrics need host network stack              │
│  - Battery/power awareness needs host APIs            │
│  - Latency measurements distorted by container NAT    │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  CONTAINER (optional): beacon-shipper                 │
│  Runs as: unprivileged sidecar                        │
│                                                       │
│  Responsibilities:                                    │
│  - Batch export to remote backends                    │
│  - Prometheus remote_write / OTLP conversion          │
│  - Retry queue for failed exports                     │
│  - Compression + batching                             │
│                                                       │
│  Why separate:                                        │
│  - Export logic shouldn't block telemetry collection   │
│  - Can be replaced by Telegraf, Vector, or OTel agent │
│  - Simplifies the host process                        │
└──────────────────────────────────────────────────────┘
```

For single-host AIO deployments (Pi / NUC), both run on the host. The shipper
is an optional optimization for fleet deployments.

### Local Buffer: SQLite WAL

SQLite in WAL (Write-Ahead Log) mode is the local buffer. Why not Parquet:

| | SQLite WAL | Parquet |
|---|---|---|
| Writes | Fast append, no blocking reads | Batch-oriented, needs flush |
| Reads | Indexed queries for anomaly detection | Great for analytics, bad for real-time |
| Concurrency | Writer + multiple readers | Single writer |
| Crash safety | WAL journaling | Depends on flush timing |
| Footprint | ~2MB library (already in Python stdlib) | Requires pyarrow (~150MB) |
| Retention | Easy DELETE WHERE timestamp < X | Requires file rotation |

**Schema**:
```sql
CREATE TABLE telemetry_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    measurement TEXT NOT NULL,
    timestamp TEXT NOT NULL,          -- ISO 8601
    tags TEXT NOT NULL,               -- JSON
    fields TEXT NOT NULL,             -- JSON
    event_type TEXT,                  -- NULL for metrics
    tier INTEGER NOT NULL DEFAULT 0,
    exported INTEGER NOT NULL DEFAULT 0,  -- 0=pending, 1=exported
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_telemetry_ts ON telemetry_points(timestamp);
CREATE INDEX idx_telemetry_measurement ON telemetry_points(measurement, timestamp);
CREATE INDEX idx_telemetry_export ON telemetry_points(exported, created_at);
```

**Retention**: Compact every hour. Delete exported points older than 24h.
Delete unexported points older than 7 days. Hard cap at 50MB — evict oldest
when exceeded.

### Export Methods

**InfluxDB Line Protocol** (default, already supported):
```
t_wifi_link,host_id=beacon-01,interface=en0,tier=0 rssi_dbm=-52,noise_dbm=-90,snr_db=38 1707660600000000000
```

**Prometheus remote_write**:
```
# Mapped as:
beacon_wifi_link_rssi_dbm{host_id="beacon-01",interface="en0",tier="0"} -52 1707660600
beacon_wifi_link_noise_dbm{host_id="beacon-01",interface="en0",tier="0"} -90 1707660600
```

Mapping rule: `{measurement}_{field_name}` becomes the Prometheus metric name.
Tags become labels. One time-series per field (Prometheus is single-value).

**OTLP Metrics** (gRPC):
```protobuf
// Mapped as OTLP Gauge:
Resource { host.id: "beacon-01" }
Metric {
  name: "t_wifi_link.rssi_dbm"
  gauge { data_points: [{ value: -52, time: ..., attributes: { interface: "en0" } }] }
}
```

### Offline Handling

When no export backend is reachable:

1. Points accumulate in SQLite buffer (exported=0).
2. Exporter retries with exponential backoff (1s → 2s → 4s → ... → 60s max).
3. When backend reconnects, batch-export pending points (oldest first).
4. If buffer hits 50MB cap, evict oldest unexported points (warn in logs).
5. Never block sampling — buffer overflow drops data, never stalls collection.

### Resource Guardrails

```yaml
resource_limits:
  cpu:
    soft_limit_pct: 5       # Reduce sampling frequency above this
    hard_limit_pct: 10      # Pause Tier 1+2, Tier 0 only at minimum frequency

  memory:
    buffer_max_mb: 100      # Ring buffer + aggregator state
    sqlite_max_mb: 50       # Local buffer cap

  battery:
    # macOS: IOPowerSources API via psutil
    # Linux: /sys/class/power_supply/
    low_threshold_pct: 20   # Below this: Tier 0 only, 60s minimum interval
    critical_threshold_pct: 10  # Below this: suspend telemetry entirely
    on_ac_only_tiers: [2]   # Tier 2 stress probes only on AC power

  network:
    metered_connection:       # Detected via networksetup (macOS) or nmcli (Linux)
      disable_tiers: [2]     # No stress probes on metered
      reduce_export_batch: true  # Batch exports every 5 min instead of 30s
```

---

## Deliverables Summary

### Complete Metric List

#### Tier 0 — Baseline (always-on)

| # | Measurement | Field | Unit | Interval | Aggregation |
|---|---|---|---|---|---|
| 1 | `t_wifi_link` | `rssi_dbm` | dBm | 30s | last |
| 2 | | `noise_dbm` | dBm | 30s | last |
| 3 | | `snr_db` | dB | 30s | last |
| 4 | | `tx_rate_mbps` | Mbps | 30s | last |
| 5 | | `mcs_index` | index | 30s | last |
| 6 | `t_gateway_rtt` | `rtt_p50_ms` | ms | 10s → 60s | percentile |
| 7 | | `rtt_p95_ms` | ms | | percentile |
| 8 | | `rtt_p99_ms` | ms | | percentile |
| 9 | | `loss_pct` | % | | mean |
| 10 | | `jitter_ms` | ms | | stddev of RTTs |
| 11 | `t_internet_rtt` | `rtt_p50_ms` | ms | 10s → 60s | percentile |
| 12 | | `rtt_p95_ms` | ms | | percentile |
| 13 | | `rtt_p99_ms` | ms | | percentile |
| 14 | | `loss_pct` | % | | mean |
| 15 | | `jitter_ms` | ms | | stddev |
| 16 | `t_dns_latency` | `latency_p50_ms` | ms | 30s → 60s | percentile |
| 17 | | `latency_p95_ms` | ms | | percentile |
| 18 | | `latency_p99_ms` | ms | | percentile |
| 19 | | `success_rate` | ratio | | mean |
| 20 | | `timeout_count` | count | | sum |
| 21 | `t_http_timing` | `dns_ms` | ms | 60s | per-request |
| 22 | | `connect_ms` | ms | | per-request |
| 23 | | `tls_ms` | ms | | per-request |
| 24 | | `ttfb_ms` | ms | | per-request |
| 25 | | `total_ms` | ms | | per-request |
| 26 | | `status_code` | code | | per-request |
| 27 | `t_device_health` | `cpu_pct` | % | 30s → 60s | mean |
| 28 | | `mem_pct` | % | | last |
| 29 | | `load_1m` | load | | last |

#### Tier 1 — Enhanced (on escalation or configured always-on)

| # | Measurement | Field | Unit | Interval |
|---|---|---|---|---|
| 30 | `t_wifi_quality` | `retry_pct` | % | 15s |
| 31 | | `tx_failures` | count/window | 15s |
| 32 | | `rx_errors` | count/window | 15s |
| 33 | | `rate_shift_count` | count/window | 15s |
| 34 | `t_wifi_channel` | `utilization_pct` | % | 30s |
| 35 | | `airtime_busy_pct` | % | 30s |
| 36 | | `noise_floor_dbm` | dBm | 30s |
| 37 | `t_tls_timing` | `handshake_ms` | ms | 60s |
| 38 | | `protocol_version` | string | 60s |
| 39 | `t_vpn_tunnel` | `mtu` | bytes | 60s |
| 40 | | `overhead_ms` | ms | 60s |

#### Tier 2 — Experience (triggered / scheduled)

| # | Measurement | Field | Unit | Trigger |
|---|---|---|---|---|
| 41 | `t_bufferbloat` | `idle_rtt_ms` | ms | sched/anomaly |
| 42 | | `loaded_rtt_ms` | ms | |
| 43 | | `bloat_ms` | ms | |
| 44 | | `download_mbps` | Mbps | |
| 45 | | `upload_mbps` | Mbps | |
| 46 | | `responsiveness_rpm` | rpm | |
| 47 | `t_saas_probe` | `ttfb_ms` | ms | scheduled |
| 48 | | `total_ms` | ms | |
| 49 | `t_route_snapshot` | `hop_count` | count | 5min/anomaly |
| 50 | | `timeout_hops` | count | |
| 51 | | `path_hash` | hash | |

### Default Sampling Intervals

| Tier | Measurement | Normal Interval | Escalated Interval |
|---|---|---|---|
| 0 | Wi-Fi link | 30s | 10s |
| 0 | Gateway ping | 10s (3 probes) | 5s (3 probes) |
| 0 | Internet ping | 10s (3 probes) | 5s (3 probes) |
| 0 | DNS latency | 30s | 10s |
| 0 | HTTP timing | 60s | 30s |
| 0 | Device health | 30s | 15s |
| 0 | Change detection | 30s (poll) | 10s (poll) |
| 1 | Wi-Fi quality | 15s | 5s |
| 1 | Wi-Fi channel | 30s | 15s |
| 1 | TLS timing | 60s | 30s |
| 1 | VPN tunnel | 60s | 30s |
| 2 | Bufferbloat | — | one-shot per trigger |
| 2 | SaaS probes | 5min (if scheduled) | one-shot per trigger |
| 2 | Route snapshot | 5min | one-shot per trigger |
| 2 | Burst sampling | — | 1s for 60-120s |

### Example YAML Config: Telemetry Mode

```yaml
# beacon.yaml — telemetry mode configuration

beacon:
  host: "0.0.0.0"
  port: 8000
  probe_id: "probe-hq-3f"
  mode: "telemetry"          # "diagnostic" (default) | "telemetry" | "both"

telemetry:
  enabled: true

  # ── Tier Configuration ──────────────────────────────────────
  tiers:
    tier_0:
      enabled: true           # Always true in telemetry mode
      wifi:
        interval_seconds: 30
        method: "auto"        # auto | system_profiler | wdutil | airport
      gateway:
        interval_seconds: 10
        probes_per_sample: 3
      internet:
        interval_seconds: 10
        probes_per_sample: 3
        targets:
          - { address: "8.8.8.8", name: "google_dns" }
          - { address: "1.1.1.1", name: "cloudflare_dns" }
      dns:
        interval_seconds: 30
        resolvers: ["8.8.8.8", "1.1.1.1", "9.9.9.9"]
        domains: ["google.com", "cloudflare.com"]
      http:
        interval_seconds: 60
        method: "HEAD"
        targets:
          - "https://www.google.com"
          - "https://www.cloudflare.com"
      device:
        interval_seconds: 30
      change_detection:
        poll_interval_seconds: 30

    tier_1:
      enabled: false          # Enabled on escalation (or set true for always-on)
      always_on: false        # Override: keep Tier 1 running even at baseline
      wifi_quality:
        interval_seconds: 15
      wifi_channel:
        interval_seconds: 30
      tls_timing:
        interval_seconds: 60
        targets:
          - "https://www.google.com"
      vpn:
        interval_seconds: 60

    tier_2:
      enabled: true           # Available for triggering (not always-on)
      bufferbloat:
        method: "networkQuality"  # networkQuality (macOS) | iperf3
        schedule: null            # null = anomaly-triggered only
        # schedule: "0 */4 * * *"  # cron: every 4 hours
      saas_probes:
        schedule: "*/5 * * * *"   # every 5 minutes
        endpoints:
          - { service: "microsoft365", url: "https://outlook.office365.com" }
          - { service: "github", url: "https://api.github.com" }
      route_snapshot:
        interval_seconds: 300
        targets: ["8.8.8.8"]
      burst:
        duration_seconds: 120
        sample_interval_seconds: 1

  # ── Window Aggregation ──────────────────────────────────────
  aggregation:
    window_seconds: 60
    percentiles: [50, 95, 99]
    raw_buffer_minutes: 10     # Keep raw samples for anomaly lookback

  # ── Privacy ─────────────────────────────────────────────────
  privacy:
    mode: "hashed"             # hashed | redacted | plaintext
    hash_salt: ""              # Empty = plain SHA-256

  # ── Local Buffer ────────────────────────────────────────────
  buffer:
    backend: "sqlite"
    path: "./data/telemetry.db"
    max_size_mb: 50
    retention_days: 7
    compact_interval_minutes: 60

  # ── Export ──────────────────────────────────────────────────
  export:
    # Multiple exporters can run simultaneously
    influxdb:
      enabled: true
      url: "http://localhost:8086"
      token: "beacon-dev-token"
      org: "beacon"
      bucket: "beacon_telemetry"  # Separate bucket from diagnostic data
      batch_size: 100
      flush_interval_seconds: 30

    prometheus:
      enabled: false
      remote_write_url: "https://prometheus.example.com/api/v1/write"
      batch_size: 500
      flush_interval_seconds: 30
      metric_prefix: "beacon_"

    otlp:
      enabled: false
      endpoint: "localhost:4317"
      protocol: "grpc"           # grpc | http
      compression: "gzip"
      batch_size: 200
      flush_interval_seconds: 30

    file:
      enabled: false
      path: "./data/telemetry.jsonl"
      rotate_size_mb: 10
      rotate_count: 5

  # ── Resource Guardrails ─────────────────────────────────────
  resources:
    cpu_soft_limit_pct: 5
    cpu_hard_limit_pct: 10
    memory_max_mb: 100
    battery_low_pct: 20
    battery_critical_pct: 10
    pause_on_metered: true
```

### Example Trigger Config

```yaml
# triggers.yaml — escalation trigger rules

triggers:
  # ── Wi-Fi Triggers ────────────────────────────────────
  rssi_drop:
    description: "RSSI dropped >10 dB in 30 seconds"
    measurement: "t_wifi_link"
    condition:
      type: "delta"
      field: "rssi_dbm"
      window_seconds: 30
      threshold: -10            # dB (negative = drop)
      direction: "below"
    escalate_to: "elevated"
    cooldown_seconds: 60
    severity: "warning"

  weak_signal_sustained:
    description: "RSSI below -75 dBm for 2+ minutes"
    measurement: "t_wifi_link"
    condition:
      type: "sustained"
      field: "rssi_dbm"
      threshold: -75
      direction: "below"
      sustain_seconds: 120
    escalate_to: "elevated"
    cooldown_seconds: 120
    severity: "warning"

  roam_storm:
    description: "3+ roams in 5 minutes"
    measurement: "t_wifi_roam"
    condition:
      type: "event_count"
      event_type: "wifi_roam"
      window_seconds: 300
      threshold: 3
    escalate_to: "active"
    cooldown_seconds: 120
    severity: "warning"

  # ── Network Triggers ──────────────────────────────────
  sustained_loss:
    description: "Packet loss >3% sustained for 60 seconds"
    measurement: "t_internet_rtt"
    condition:
      type: "sustained"
      field: "loss_pct"
      threshold: 3.0
      direction: "above"
      sustain_seconds: 60
    escalate_to: "elevated"
    cooldown_seconds: 60
    severity: "warning"

  gateway_unreachable:
    description: "Gateway completely unreachable"
    measurement: "t_gateway_rtt"
    condition:
      type: "threshold"
      field: "loss_pct"
      threshold: 100.0
      direction: "above_or_equal"
    escalate_to: "active"
    cooldown_seconds: 30
    severity: "critical"

  jitter_spike:
    description: "Internet jitter exceeds 50ms"
    measurement: "t_internet_rtt"
    condition:
      type: "threshold"
      field: "jitter_ms"
      threshold: 50.0
      direction: "above"
    escalate_to: "elevated"
    cooldown_seconds: 60
    severity: "warning"

  # ── DNS Triggers ──────────────────────────────────────
  dns_latency_spike:
    description: "DNS p95 latency exceeds 200ms"
    measurement: "t_dns_latency"
    condition:
      type: "threshold"
      field: "latency_p95_ms"
      threshold: 200.0
      direction: "above"
    escalate_to: "elevated"
    cooldown_seconds: 60
    severity: "warning"

  dns_failures:
    description: "DNS success rate below 90%"
    measurement: "t_dns_latency"
    condition:
      type: "threshold"
      field: "success_rate"
      threshold: 0.9
      direction: "below"
    escalate_to: "active"
    cooldown_seconds: 60
    severity: "critical"

  # ── HTTP Triggers ─────────────────────────────────────
  http_ttfb_spike:
    description: "HTTP TTFB exceeds 2 seconds"
    measurement: "t_http_timing"
    condition:
      type: "threshold"
      field: "ttfb_ms"
      threshold: 2000.0
      direction: "above"
    escalate_to: "elevated"
    cooldown_seconds: 60
    severity: "warning"

  # ── Infrastructure Triggers ───────────────────────────
  route_change:
    description: "Default route changed"
    condition:
      type: "event"
      event_type: "route_change"
    escalate_to: "active"
    cooldown_seconds: 30
    severity: "warning"

  dns_server_change:
    description: "DNS resolver configuration changed"
    condition:
      type: "event"
      event_type: "dns_server_change"
    escalate_to: "elevated"
    cooldown_seconds: 30
    severity: "info"

# ── Global Escalation Settings ────────────────────────
escalation:
  flap_guard:
    max_triggers_per_window: 3
    window_minutes: 10
    action: "extend_cooldown"     # extend_cooldown | suppress_tier2
    extended_cooldown_seconds: 300

  auto_pack:
    enabled: true
    on_state: "active"            # Generate diagnostic pack on ACTIVE
    pack_name: "full_diagnostic"
    max_auto_packs_per_hour: 2
```

### Resource Impact Estimates

| Tier | CPU (sustained) | Memory | Disk (per day) | Network (outbound) | Battery Impact |
|---|---|---|---|---|---|
| **Tier 0 only** | <1% | ~20 MB | ~3 MB | ~3 MB | Negligible |
| **Tier 0 + 1** | ~2-3% | ~35 MB | ~12 MB | ~12 MB | Minor (<1% drain/hr) |
| **Tier 0 + 1 + 2 burst** | ~10-15% (120s) | ~50 MB | ~1 MB per burst | ~1 MB per burst | Noticeable during burst |
| **Tier 2 bufferbloat** | ~15-20% (30s) | ~30 MB | ~0.5 MB | 10-50 MB (load test) | Significant (brief) |
| **Local buffer (SQLite)** | <0.5% | ~5 MB | Capped at 50 MB total | 0 | Negligible |
| **Export pipeline** | <0.5% | ~10 MB | 0 | Same as disk but compressed | Negligible |

**Comparison**: Apple's built-in Wi-Fi diagnostics background process uses ~2-5% CPU.
Beacon Tier 0 targets <1%. A web browser tab uses more.

### Escalation Flow (Narrative)

**14:30:00** — Baseline. Tier 0 sampling humming along. Wi-Fi RSSI steady at
-52 dBm, gateway ping 4ms, DNS 5ms. All good.

**14:30:30** — Wi-Fi sample: RSSI dropped to -67 dBm. The `rssi_drop` trigger
evaluates: delta of -15 dB in 30 seconds exceeds the -10 dB threshold.

**14:30:30** — Escalation: BASELINE → ELEVATED.
- Tier 1 collectors activate (Wi-Fi quality, channel utilization).
- Tier 0 ping interval increases from 10s to 5s.
- `anomaly_trigger` event emitted to telemetry stream.

**14:30:45** — Tier 1 data arrives: retry rate 12%, tx failures climbing.
Channel utilization at 78%. A `wifi_roam` event fires — BSSID changed.

**14:31:00** — Second roam detected. `roam_storm` trigger is watching.

**14:31:30** — Third roam in 90 seconds. `roam_storm` fires (3+ in 5 min).

**14:31:30** — Escalation: ELEVATED → ACTIVE.
- Burst sampling starts: all Tier 0 metrics at 1s interval.
- Traceroute burst runs to all configured targets.
- Auto-pack triggered: `full_diagnostic` runs in background.
- `escalation_active` event emitted.

**14:33:30** — Burst window expires (120s). Escalation: ACTIVE → COOLDOWN.
- Burst sampling stops.
- Tier 2 probes stop.
- Tier 0 + 1 continue.
- Evidence pack saved: `evidence/auto-14:31:30-roam_storm.json`

**14:34:30** — Cooldown expires (60s). Metrics show RSSI stabilized at -58 dBm,
roaming stopped, retry rate back to 0.2%.

**14:34:30** — Escalation: COOLDOWN → BASELINE.
- Tier 1 disabled (unless `always_on: true`).
- Normal intervals restored.
- `escalation_resolved` event emitted.

The entire incident — from first RSSI drop to resolution — is captured in
the telemetry stream with window-aggregated metrics, discrete events, and
a linked evidence pack. A dashboard query for `t_anomaly` events shows the
timeline. The evidence pack provides the deep snapshot.

---

## Implementation Phases (Recommended)

### Phase A: Core Telemetry Loop
- `TelemetrySampler` base class (analogous to `BaseCollector`)
- `TelemetryScheduler` (asyncio event loop with per-sampler intervals)
- `WindowAggregator` (ring buffer + percentile computation)
- Tier 0 samplers only (Wi-Fi, ping, DNS, HTTP, device)
- SQLite local buffer
- InfluxDB export

### Phase B: Change Detection + Events
- Route/DNS/IP/SSID polling with diff-based event emission
- Event storage in SQLite buffer alongside metrics
- Basic anomaly detection (threshold triggers only)

### Phase C: Escalation Engine
- State machine (BASELINE → ELEVATED → ACTIVE → COOLDOWN)
- Trigger rule evaluation per window cycle
- Dynamic interval adjustment
- Flap guard

### Phase D: Tier 1 + 2 Collectors
- Privileged Wi-Fi quality sampling (wdutil / iw station dump)
- Roam tracking and deauth monitoring
- Bufferbloat testing (networkQuality / iperf3)
- SaaS endpoint probes
- Burst sampling mode

### Phase E: Export Pipeline
- Prometheus remote_write exporter
- OTLP/gRPC exporter
- Batch retry queue
- Compression

### Phase F: Resource Governor + Battery Awareness
- CPU monitoring and throttling
- Battery state detection (psutil / platform APIs)
- Metered connection detection
- Graceful degradation

---

## Open Questions

1. **Telemetry CLI**: Should `beacon telemetry start` be a foreground process
   or a daemon? macOS has `launchd`, Linux has `systemd`. A foreground
   process is simpler for MVP but a daemon is needed for production.

2. **Schema registry**: As telemetry measurements evolve, how do we version
   them? A `t_` prefix distinguishes telemetry from diagnostic measurements,
   but field additions/removals need a migration strategy for InfluxDB.

3. **Multi-probe correlation**: With multiple Beacon probes on a network,
   can we correlate their telemetry? If probe-A and probe-B both see DNS
   spikes at the same time, that's stronger signal than one probe alone.
   This is a backend/query concern, not a collection concern.

4. **Alert routing**: Telemetry detects anomalies, but who gets notified?
   This design covers detection and evidence capture. Alerting (PagerDuty,
   Slack, email) is a separate concern, likely handled by the export
   backend (Grafana alerting, Prometheus Alertmanager).
