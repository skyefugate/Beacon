---
mode: always
---

# Product Vision — Beacon

## Mission

Turn subjective "it's slow" complaints into repeatable, evidence-based network diagnostics.

Beacon provides **continuous observability** and **on-demand diagnostics** for network environments where traditional monitoring fails: home networks, remote workers, mobile devices, WiFi-heavy deployments.

## Core Value Propositions

### 1. Evidence-Based Troubleshooting

**Problem**: Users report "the internet is slow" without actionable data.

**Solution**: Structured evidence packs with:
- Network topology snapshots
- Latency/throughput measurements
- WiFi signal quality metrics
- DNS/HTTP/TLS timing breakdowns
- Fault domain correlation (WiFi vs ISP vs DNS vs application)

### 2. Privacy-Preserving Telemetry

**Problem**: Network monitoring exposes sensitive identifiers (SSIDs, BSSIDs, URLs).

**Solution**: Three privacy modes:
- **Hashed** (default): SHA-256 hashed SSIDs/BSSIDs, role-tagged IPs
- **Redacted**: All identifiers replaced with `[redacted]`
- **Plaintext**: Full visibility (opt-in only)

### 3. Resource-Conscious Monitoring

**Problem**: Always-on monitoring drains battery and interferes with real workloads.

**Solution**: 3-tier escalation system:
- **Tier 0**: Lightweight baseline (<1% CPU, 5-60s intervals)
- **Tier 1**: Enhanced context on anomaly detection
- **Tier 2**: Active probing only when necessary (bufferbloat, traceroute)

### 4. Modular and Extensible

**Problem**: Every environment has unique monitoring needs.

**Solution**: Plugin architecture for:
- Custom collectors (passive observation)
- Custom runners (active tests)
- Custom diagnostic packs (YAML-defined workflows)
- Multiple export targets (InfluxDB, Prometheus, OTLP, files)

## Deployment Architecture

### Endpoint Agents (Native Host Processes)

**Primary deployment**: Native binaries running directly on endpoints.

**Why**: WiFi radio metrics, system-level network access, low overhead.

**Platforms**: macOS (launchd), Linux (systemd), Windows (future).

**No Docker required** on endpoints.

### Backend Services (Docker Only)

**Components**:
- Frontend dashboard (React)
- InfluxDB time-series database
- Aggregation services (future)

**Why Docker**: Easy deployment, isolation, version management.

**Deployment**: `docker-compose` for local/small deployments, Kubernetes for scale.

## Target Users

### Primary: Network Support Teams

- Help desk staff troubleshooting remote worker issues
- IT teams managing distributed office networks
- MSPs supporting customer environments

**Needs**: Repeatable diagnostics, evidence for escalation, root cause identification.

### Secondary: Power Users

- Remote workers with chronic connectivity issues
- Developers debugging application performance
- Home network enthusiasts

**Needs**: Self-service diagnostics, historical trend analysis, WiFi optimization.

### Future: SaaS Providers

- Application vendors diagnosing "your service is slow" reports
- VPN providers validating tunnel performance
- ISPs identifying last-mile issues

**Needs**: Automated evidence collection, API integration, privacy compliance.

## Non-Goals

### What Beacon Is Not

- **Not a full APM**: No application tracing, no code instrumentation
- **Not a packet analyzer**: No deep packet inspection, no protocol decoding
- **Not a security tool**: No intrusion detection, no vulnerability scanning
- **Not a bandwidth hog**: No continuous throughput testing, no iperf3 loops

### Explicit Limitations

- **WiFi-Centric**: Optimized for wireless environments, not data centers
- **Client-Side**: Monitors from endpoint perspective, not network infrastructure
- **Diagnostic-First**: Designed for troubleshooting, not capacity planning
- **Privacy-Bounded**: No URL logging, no payload inspection

## Success Metrics

### User Outcomes

- **Time to Root Cause**: Reduce from hours to minutes
- **Evidence Quality**: Eliminate "works on my machine" debates
- **Support Efficiency**: Reduce back-and-forth diagnostic requests

### Technical Metrics

- **Resource Overhead**: <1% CPU in Tier 0, <5% in Tier 2
- **Battery Impact**: <2% daily drain on laptops
- **Storage Efficiency**: <100MB/day telemetry data
- **Privacy Compliance**: Zero plaintext identifiers in default mode

### Adoption Signals

- **Self-Service Rate**: Users run diagnostics before contacting support
- **Evidence Attachment**: Support tickets include Beacon evidence packs
- **Repeat Usage**: Users enable continuous telemetry mode

## Roadmap Phases

### v1.0 — Full Observability (Current)

- Complete diagnostic pack system
- 3-tier telemetry escalation
- Native agent deployment (macOS, Linux)
- React dashboard with real-time metrics
- Privacy-preserving evidence packs

### v1.1 — Intelligence Layer

- Anomaly detection triggers
- Advanced fault domain correlation
- Export pipeline (Prometheus, OTLP)
- Self-diagnostics (`beacon doctor`)
- Config reload without restart

### v2.0 — Multi-Device Correlation

- Household/office-wide monitoring
- Cross-device roaming analysis
- Shared evidence repositories
- Centralized dashboard

### Future — SaaS Integration

- Vendor-specific endpoint testing
- API for external tool integration
- Managed backend service option
- Compliance reporting (GDPR, CCPA)

## Design Principles

### 1. Native-First for Endpoints

Agents run as native processes, not containers. Direct system access for WiFi metrics and network operations.

### 2. Operational Honesty

Report what we measure, not what we infer. Confidence scores for correlations.

### 3. Fail Gracefully

Single sampler failures must not crash telemetry loop. Degraded data is better than no data.

### 4. Privacy by Default

Hashed mode is default. Plaintext requires explicit opt-in.

### 5. Resource-Aware

Respect CPU/memory/battery limits. Monitoring must not interfere with real work.

### 6. Extensible Without Chaos

Plugin system with stable interfaces. New collectors/runners don't require core changes.
