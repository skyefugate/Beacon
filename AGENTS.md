# Agent Operating Rules — Beacon

## Repository Purpose

Beacon is a network diagnostics and observability platform with two operational modes:

1. **Diagnostic Mode**: Point-in-time network snapshots via configurable test packs
2. **Telemetry Mode**: Continuous monitoring with 3-tier escalation (baseline → enhanced → active probing)

**Core Capabilities**: WiFi monitoring, DNS/HTTP/TLS checks, latency analysis, fault domain correlation, privacy-preserving telemetry, evidence pack generation.

**Deployment Models**:
- **Endpoint agents**: Native host processes (macOS launchd, Linux systemd)
- **Backend services**: Docker containers (React dashboard, InfluxDB)

## Architecture Boundaries

### Component Layers (Do Not Collapse)

- **Collectors** (`src/beacon/collectors/`): Passive observation (WiFi, device, LAN topology)
- **Runners** (`src/beacon/runners/`): Active tests (ping, DNS, HTTP, traceroute, throughput)
- **Telemetry Engine** (`src/beacon/telemetry/`): Continuous monitoring, escalation, anomaly detection
- **Pack System** (`src/beacon/packs/`): YAML-based test orchestration
- **Storage** (`src/beacon/storage/`): InfluxDB persistence, artifact management
- **API** (`src/beacon/api/`): FastAPI REST endpoints (future backend service)
- **CLI** (`src/beacon/cli/`): Typer-based command interface
- **UI** (`ui/`): React/TypeScript dashboard

### Deployment Separation

**Native Agent** (runs on endpoints):
- Collectors, runners, telemetry scheduler, CLI
- Direct system access for WiFi metrics and network operations
- No Docker required

**Backend Services** (Docker only):
- React dashboard
- InfluxDB database
- Future aggregation API

**Never** require Docker for endpoint agent functionality.

## Allowed Edit Zones

### Safe to Modify

- **Collectors**: Add new collectors in `src/beacon/collectors/` following registry pattern
- **Runners**: Add new runners in `src/beacon/runners/` following registry pattern
- **Packs**: Create new YAML pack definitions in `packs/`
- **Tests**: Add tests in `tests/` matching source structure
- **Documentation**: Update `docs/`, inline docstrings
- **UI Components**: Add React components in `ui/src/components/`

### Requires Careful Review

- **Telemetry Scheduler** (`src/beacon/telemetry/scheduler.py`): Affects resource management
- **Storage Layer** (`src/beacon/storage/`): Schema changes impact data persistence
- **API Endpoints** (`src/beacon/api/`): Breaking changes affect external integrations
- **Privacy Logic** (`src/beacon/models/privacy.py`): Security-sensitive hashing/redaction
- **Installation Scripts** (`scripts/`): Affects deployment and upgrades

### Restricted (High Risk)

- **Escalation Engine** (`src/beacon/telemetry/escalation.py`): Core monitoring logic
- **Fault Domain Analysis** (`src/beacon/engine/`): Correlation algorithms
- **Resource Governors**: CPU/memory/battery guardrails must not be weakened
- **Privilege Requirements**: Never add unnecessary root/elevated permissions

## Test and Validation Expectations

### Required for All Changes

1. **Linting**: `ruff check src/ tests/` must pass (line length: 100 chars)
2. **Type Checking**: `mypy src/` must pass (strict mode)
3. **Unit Tests**: `pytest tests/` must pass with >80% coverage
4. **Kiro Hooks**: Use `beacon-dev` agent for automated formatting/testing (see `docs/development-workflow.md`)

### Test Structure

- Mirror source structure: `tests/collectors/test_wifi.py` ↔ `src/beacon/collectors/wifi.py`
- Use pytest fixtures for common setup (InfluxDB mocks, config objects)
- Mock external dependencies (network calls, system commands)
- Test both success and failure paths

### Integration Tests

- Place in `tests/integration/`
- Test cross-component workflows (pack execution, telemetry pipeline)
- Mark with `@pytest.mark.integration`

## Documentation Expectations

### Code Documentation

- **Docstrings**: All public functions, classes, methods (Google style)
- **Type Hints**: Required for all function signatures
- **Inline Comments**: Explain non-obvious logic, especially platform-specific code

### User Documentation

- **README Updates**: When adding user-facing features
- **Pack Examples**: Include sample YAML when adding runners/collectors
- **API Docs**: FastAPI auto-generates OpenAPI, but add endpoint descriptions

### Architecture Documentation

- **Design Docs**: Major changes require `docs/` markdown file
- **Telemetry Design**: Reference `docs/telemetry-v2-design.md` for monitoring changes

## Refactor Rules

### Plugin System

New collectors/runners must:
1. Inherit from base class (`BaseCollector`, `BaseRunner`)
2. Register via decorator (`@collector_registry.register`, `@runner_registry.register`)
3. Implement required methods (`collect()`, `run()`)
4. Return structured Pydantic models
5. Handle platform-specific logic gracefully (macOS vs Linux)

### Async Patterns

- Use `asyncio` for I/O-bound operations
- Avoid blocking calls in telemetry samplers
- Use `asyncio.create_task()` for concurrent operations
- Properly handle task cancellation

### Error Handling

- Catch specific exceptions, not bare `except:`
- Log errors with context (collector name, test parameters)
- Return structured error responses (Pydantic models with `success: bool`)
- Never crash the telemetry loop on single sampler failure

## Schema and Compatibility Rules

### Evidence Pack Schema

- **Versioned**: Include `schema_version` in all evidence packs
- **Backward Compatible**: New fields are additive only
- **Privacy-Aware**: Default to hashed mode for SSIDs/BSSIDs
- **Structured**: Use Pydantic models, not raw dicts

### InfluxDB Schema

- **Measurement Names**: Use `beacon_` prefix (e.g., `beacon_wifi_quality`)
- **Tags**: Immutable identifiers (device_id, ssid_hash, interface)
- **Fields**: Mutable metrics (rssi, latency, throughput)
- **Timestamps**: Nanosecond precision

### Configuration Schema

- **YAML-Based**: Use Pydantic models for validation
- **Environment Overrides**: Support `BEACON_*` env vars
- **Defaults**: Provide sensible defaults for all optional fields
- **Validation**: Fail fast on invalid config at startup

## Proposing Significant Changes

### Definition of "Significant"

- Changes to deployment model (native vs Docker)
- New external dependencies
- Breaking API changes
- Telemetry escalation logic modifications
- Resource governor adjustments
- Privacy model changes

### Proposal Process

1. **Open GitHub Issue**: Describe problem, proposed solution, alternatives
2. **Design Doc**: For complex changes, write `docs/proposals/NNNN-title.md`
3. **Prototype**: Implement in feature branch with tests
4. **Review**: Tag maintainers for architectural review
5. **Merge**: Only after approval and CI passing

### What to Include

- **Problem Statement**: What issue are we solving?
- **Proposed Solution**: Technical approach with code examples
- **Alternatives Considered**: Why not other approaches?
- **Impact Analysis**: What breaks? Migration path?
- **Testing Strategy**: How to validate the change?

## Current Development Focus (2026-03)

### v1.0 Priorities (Full Observability)

- Config reload without daemon restart (SIGHUP handling) - Issue #57
- Self-diagnostics command (`beacon doctor`) - Issue #66
- WiFi roaming correlation (extended time windows) - Issue #64
- Beacon frame loss monitoring - Issue #62
- Sleep/wake event handling - Issue #21

### v1.1 Priorities (Intelligence Layer)

- Advanced fault domain correlation
- Anomaly detection triggers
- Export pipeline (Prometheus, OTLP)
- Resource governance refinements

### Known Issues

- GitHub Actions: Action version errors (use @v4/@v5, not @v6)
- CI: No dependency caching, missing security scanning
- Release workflow: Fragile changelog parsing

## Quick Reference

**Add Collector**: See `.kiro/skills/add-collector.md`  
**Add Runner**: See `.kiro/skills/add-runner.md`  
**Create Pack**: See `.kiro/skills/create-diagnostic-pack.md`  
**Product Vision**: See `.kiro/steering/product.md`  
**Architecture**: See `.kiro/steering/architecture.md`  
**Testing**: See `.kiro/steering/testing-standards.md`  
**API Design**: See `.kiro/steering/api-standards.md`  
**Development Workflow**: See `docs/development-workflow.md`
