---
mode: always
---

# Architecture — Beacon

## System Overview

Beacon is a **modular network diagnostics platform** with two operational modes:

1. **Diagnostic Mode**: On-demand test pack execution
2. **Telemetry Mode**: Continuous monitoring with escalation

Both modes share common infrastructure: collectors, runners, storage, and evidence generation.

## Deployment Architecture

### Endpoint Agents (Native Processes)

**What runs on endpoints**:
- Beacon agent binary (Python or compiled)
- Collectors (WiFi, device, LAN)
- Runners (ping, DNS, HTTP, traceroute)
- Telemetry scheduler
- Local evidence storage

**Why native, not Docker**:
- Direct WiFi radio access (containers can't read RSSI/SNR on most platforms)
- System-level network operations (raw sockets, interface enumeration)
- Lower resource overhead
- Simpler installation (Homebrew, apt, MSI)

**Deployment**:
- macOS: `launchd` daemon
- Linux: `systemd` service
- Windows: Windows Service (future)

**Privileges**: Runs as root or with `CAP_NET_RAW`/`CAP_NET_ADMIN` for network operations.

### Backend Services (Docker Only)

**What runs in Docker**:
- React dashboard (frontend)
- InfluxDB (time-series database)
- Aggregation API (future multi-device correlation)

**Why Docker**:
- Easy deployment and updates
- Isolation from host system
- Version management
- Portable across environments

**Deployment**: `docker-compose` for single-server, Kubernetes for scale.

## Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Endpoint Agent (Native)                   │
│  ┌────────────┐                                              │
│  │    CLI     │  (beacon run pack, beacon doctor, etc.)     │
│  └─────┬──────┘                                              │
│        │                                                      │
│  ┌─────▼─────────────────────────────────────────────────┐  │
│  │              Pack Execution Engine                     │  │
│  │  ┌──────────────┐         ┌──────────────────────┐    │  │
│  │  │  Collectors  │         │      Runners         │    │  │
│  │  │  (Passive)   │         │     (Active)         │    │  │
│  │  └──────────────┘         └──────────────────────┘    │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │           Telemetry Scheduler & Aggregator            │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │  │
│  │  │  Tier 0  │  │  Tier 1  │  │     Tier 2       │   │  │
│  │  │ Baseline │→ │ Enhanced │→ │ Active Probing   │   │  │
│  │  └──────────┘  └──────────┘  └──────────────────┘   │  │
│  └─────────────────────────┬─────────────────────────────┘  │
│                             │                                │
│  ┌──────────────────────────▼──────────────────────────┐    │
│  │  Local Storage (SQLite buffer, evidence JSON files) │    │
│  └──────────────────────────┬──────────────────────────┘    │
└─────────────────────────────┼───────────────────────────────┘
                              │ (HTTP/InfluxDB line protocol)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                Backend Services (Docker)                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  InfluxDB (time-series storage)                      │   │
│  └────────────────────────┬─────────────────────────────┘   │
│                            │                                 │
│  ┌─────────────────────────▼────────────────────────────┐   │
│  │  React Dashboard (query & visualize)                 │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Layer Responsibilities

### CLI Layer (`src/beacon/cli/`)

**Purpose**: User-facing command interface.

**Responsibilities**:
- Parse commands and arguments (Typer)
- Invoke pack execution
- Display results (tables, JSON)
- Manage daemon lifecycle

**Dependencies**: Pack engine, telemetry scheduler.

**Rules**:
- No business logic in CLI commands
- Delegate to pack engine or telemetry scheduler
- Support both interactive and scripted use

### Pack Execution Engine (`src/beacon/packs/`)

**Purpose**: Orchestrate diagnostic workflows.

**Responsibilities**:
- Parse YAML pack definitions
- Execute collectors and runners in sequence
- Aggregate results into evidence packs
- Handle timeouts and failures

**Dependencies**: Collectors, runners, storage.

**Rules**:
- Packs are declarative (YAML), not imperative
- Execution is idempotent where possible
- Failures in one step don't abort entire pack

### Collectors (`src/beacon/collectors/`)

**Purpose**: Passive observation of network state.

**Responsibilities**:
- WiFi signal quality (RSSI, SNR, TX rate)
- Device health (CPU, memory, battery)
- LAN topology (ARP, LLDP)
- Network interface configuration

**Dependencies**: Platform-specific tools (macOS `system_profiler`, Linux `iw`).

**Rules**:
- No active network traffic
- Platform-specific code isolated in separate modules
- Return structured Pydantic models
- Graceful degradation on missing tools

### Runners (`src/beacon/runners/`)

**Purpose**: Active network testing.

**Responsibilities**:
- Ping (ICMP, TCP)
- DNS resolution
- HTTP/HTTPS requests with timing
- Traceroute
- Throughput (iperf3, networkQuality)

**Dependencies**: Network access, privileged operations.

**Rules**:
- Respect resource limits (timeout, max retries)
- Return structured results with timing breakdowns
- Handle network failures gracefully
- No unbounded loops

### Telemetry Engine (`src/beacon/telemetry/`)

**Purpose**: Continuous monitoring with escalation.

**Responsibilities**:
- Schedule samplers at appropriate intervals
- Detect anomalies and trigger escalation
- Aggregate metrics for storage
- Enforce resource governors (CPU, memory, battery)

**Dependencies**: Collectors, runners, storage.

**Rules**:
- Tier 0 must be <1% CPU overhead
- Single sampler failure must not crash loop
- Escalation triggers must be configurable
- Battery-aware scheduling on laptops

### Storage Layer (`src/beacon/storage/`)

**Purpose**: Persist telemetry and evidence.

**Responsibilities**:
- InfluxDB client for time-series data
- Local SQLite buffer when InfluxDB unavailable
- Artifact storage for evidence packs (JSON files)
- Query interface for CLI and dashboard

**Dependencies**: InfluxDB 2.x (optional, buffers locally if unavailable).

**Rules**:
- Schema versioning for evidence packs
- Retention policies configurable
- Graceful handling of InfluxDB unavailability
- Never block telemetry on storage failures

### Fault Domain Engine (`src/beacon/engine/`)

**Purpose**: Correlate metrics to identify root causes.

**Responsibilities**:
- Analyze evidence packs for patterns
- Assign confidence scores to fault domains (WiFi, DNS, ISP, application)
- Generate human-readable summaries

**Dependencies**: Evidence packs, historical telemetry.

**Rules**:
- Confidence scores must be honest (no false certainty)
- Correlations are suggestions, not guarantees
- Extensible rule system for new fault types

## Data Flow

### Diagnostic Mode

```
User → CLI → Pack Engine → Collectors/Runners → Evidence Pack → Local Storage
                                                                      ↓
                                                              (optional) InfluxDB
```

### Telemetry Mode

```
Scheduler → Samplers (Tier 0/1/2) → Aggregator → SQLite Buffer → InfluxDB
                ↓
        Anomaly Detector → Escalation Trigger → Higher Tier
```

## Extension Points

### Adding Collectors

1. Inherit from `BaseCollector`
2. Implement `collect() -> CollectorResult`
3. Register via `@collector_registry.register("name")`
4. Add tests in `tests/collectors/`

### Adding Runners

1. Inherit from `BaseRunner`
2. Implement `run() -> RunnerResult`
3. Register via `@runner_registry.register("name")`
4. Add tests in `tests/runners/`

### Adding Diagnostic Packs

1. Create YAML file in `packs/`
2. Define collectors, runners, and sequence
3. Test via `beacon run pack <name>`

### Adding Export Targets

1. Implement `BaseExporter` interface
2. Add to `src/beacon/storage/exporters/`
3. Configure in `config.yaml`

## Privacy Architecture

### Identifier Hashing

**Default Mode**: SHA-256 hash with per-device salt.

**Hashed Identifiers**:
- SSIDs
- BSSIDs
- MAC addresses (non-local)

**Plaintext Identifiers**:
- IP addresses (role-tagged: gateway, dns, internet, local)
- Timestamps
- Numeric metrics

### Redaction Mode

All identifiers replaced with `[redacted]`. Useful for public evidence sharing.

### Plaintext Mode

Full visibility. Requires explicit opt-in via config flag.

## Resource Governance

### CPU Limits

- **Tier 0**: <1% average CPU
- **Tier 1**: <3% average CPU
- **Tier 2**: <5% average CPU

Enforced via sampling interval adjustments and active probe throttling.

### Memory Limits

- **Baseline**: <50MB resident
- **Peak**: <200MB during active probing

Enforced via buffer size limits and metric aggregation.

### Battery Awareness

On laptops:
- Reduce sampling frequency when on battery
- Skip Tier 2 probing when <20% battery
- Pause telemetry when <10% battery

## Security Boundaries

### Privilege Model

**Agent runs as root** (or with `CAP_NET_RAW`/`CAP_NET_ADMIN`) for:
- Raw ICMP sockets (ping)
- Network interface enumeration
- WiFi radio metrics

**Mitigation**:
- Minimal attack surface (no web server on agent)
- No external input processing in privileged code
- Config validation before privilege escalation

### Trust Model

- **User trusts Beacon**: To collect network metrics without exfiltration
- **Beacon trusts InfluxDB**: To store telemetry securely
- **Beacon does not trust network**: All external requests are suspect

### Threat Mitigation

- **Config injection**: Pydantic validation on all config inputs
- **Resource exhaustion**: Governors prevent runaway sampling
- **Data exfiltration**: No external network calls except configured targets

## Operational Constraints

### Startup Time

- **Cold start**: <5 seconds to first telemetry sample
- **Config reload**: <1 second (SIGHUP handling, in development)

### Shutdown Time

- **Graceful shutdown**: <10 seconds to flush buffers and close connections
- **Forced shutdown**: Immediate termination safe (no data corruption)

### Upgrade Path

- **In-place upgrade**: Replace binary, restart daemon
- **Schema migration**: Automatic on first run after upgrade
- **Rollback**: Previous version compatible with current data

## Future Architecture Considerations

### Multi-Device Correlation (v2.0)

- Centralized evidence repository
- Cross-device roaming analysis
- Household/office-wide dashboards

**Implications**: Need device identity management, secure aggregation backend.

### SaaS Integration (Future)

- Vendor-specific endpoint testing
- API for external tool integration
- Managed backend service option

**Implications**: Need authentication, rate limiting, multi-tenancy.
