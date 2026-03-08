---
name: create-diagnostic-pack
description: Create a new YAML-based diagnostic pack that orchestrates collectors and runners
---

# Create Diagnostic Pack Skill

Use this skill when creating a new **diagnostic pack** for Beacon.

Diagnostic packs are YAML-defined workflows that orchestrate collectors and runners to diagnose specific network issues.

## When to Use

- Creating a new troubleshooting workflow
- Combining existing collectors/runners for specific scenarios
- Building targeted diagnostics (WiFi issues, DNS problems, connectivity checks)

## Pack Structure

```yaml
name: pack_name
description: Brief description of what this pack diagnoses
version: "1.0"
privacy_mode: hashed  # hashed, redacted, or plaintext

collectors:
  - name: collector_name
    config:
      # Collector-specific configuration
      option: value

runners:
  - name: runner_name
    config:
      # Runner-specific configuration
      target: example.com
      timeout: 10

  - name: another_runner
    config:
      target: 8.8.8.8
      timeout: 5
    depends_on:
      - runner_name  # Optional: run only if previous runner succeeds

metadata:
  author: Your Name
  tags:
    - wifi
    - connectivity
  estimated_duration_seconds: 30
```

## Steps

### 1. Define Pack Purpose

Clearly identify:
- **What problem** does this pack diagnose?
- **What evidence** will it collect?
- **Who** is the target user?
- **When** should this pack be used?

### 2. Select Collectors

Choose collectors that provide relevant context:

**WiFi Issues**:
- `wifi` - Signal quality, RSSI, SNR
- `device` - CPU, memory, battery
- `network` - Interface configuration

**Connectivity Issues**:
- `network` - Interface status
- `device` - System health
- `lan` - Local network topology

**DNS Issues**:
- `network` - DNS server configuration
- `device` - System DNS cache

### 3. Select Runners

Choose runners that test specific hypotheses:

**WiFi Issues**:
- `ping` - Gateway reachability
- `dns` - DNS resolution timing
- `http` - Internet connectivity

**Connectivity Issues**:
- `ping` - Gateway, DNS, internet
- `traceroute` - Network path
- `http` - Application layer

**DNS Issues**:
- `dns` - Multiple DNS servers
- `http` - Verify resolution works end-to-end

### 4. Create Pack File

Create `packs/<name>.yaml`:

```yaml
name: wifi_troubleshoot
description: Diagnose WiFi connectivity and performance issues
version: "1.0"
privacy_mode: hashed

collectors:
  - name: wifi
    config: {}

  - name: device
    config: {}

  - name: network
    config: {}

runners:
  - name: ping
    config:
      target: gateway
      count: 10
      timeout: 5

  - name: ping
    config:
      target: 8.8.8.8
      count: 10
      timeout: 5

  - name: dns
    config:
      hostname: example.com
      server: auto
      timeout: 5

  - name: http
    config:
      url: https://www.google.com
      timeout: 10

metadata:
  author: Beacon Team
  tags:
    - wifi
    - connectivity
    - performance
  estimated_duration_seconds: 30
```

### 5. Test Pack Execution

```bash
# Execute pack locally
beacon run pack wifi_troubleshoot

# Execute with specific privacy mode
beacon run pack wifi_troubleshoot --privacy-mode plaintext

# Execute and save evidence
beacon run pack wifi_troubleshoot --output evidence.json
```

### 6. Validate Evidence Output

Check that evidence pack contains expected data:

```bash
# View evidence
cat evidence.json | jq .

# Check collectors ran
cat evidence.json | jq '.collectors | length'

# Check runners ran
cat evidence.json | jq '.runners | length'

# Check for errors
cat evidence.json | jq '.errors'
```

### 7. Create Tests

Create `tests/packs/test_<name>.py`:

```python
"""Tests for <name> diagnostic pack."""

import pytest
from beacon.packs.loader import load_pack
from beacon.packs.executor import PackExecutor


class Test<Name>Pack:
    """Tests for <name> pack."""

    def test_pack_loads(self):
        """Should load pack definition without errors."""
        pack = load_pack("<name>")

        assert pack.name == "<name>"
        assert len(pack.collectors) > 0
        assert len(pack.runners) > 0

    def test_pack_validation(self):
        """Should validate pack structure."""
        pack = load_pack("<name>")

        # Check all collectors exist
        for collector in pack.collectors:
            assert collector.name in collector_registry

        # Check all runners exist
        for runner in pack.runners:
            assert runner.name in runner_registry

    @pytest.mark.integration
    async def test_pack_execution(self, sample_config):
        """Should execute pack end-to-end."""
        pack = load_pack("<name>")
        executor = PackExecutor(config=sample_config)

        result = await executor.execute(pack)

        assert result.success is True
        assert len(result.evidence.collectors) > 0
        assert len(result.evidence.runners) > 0

    @pytest.mark.integration
    async def test_pack_execution_with_failures(self, sample_config, mock_network_down):
        """Should handle runner failures gracefully."""
        pack = load_pack("<name>")
        executor = PackExecutor(config=sample_config)

        result = await executor.execute(pack)

        # Pack should complete even if some runners fail
        assert result.success is True
        assert any(not r.success for r in result.evidence.runners)
```

### 8. Document Pack

Add to `docs/packs/<name>.md`:

```markdown
# <Name> Diagnostic Pack

## Purpose

Diagnose <specific problem> by collecting <what data> and testing <what scenarios>.

## Use Cases

- User reports <symptom>
- Troubleshooting <issue type>
- Validating <configuration>

## What It Collects

### Collectors

- **wifi**: Signal quality, RSSI, SNR, channel
- **device**: CPU, memory, battery status
- **network**: Interface configuration, DNS servers

### Runners

- **ping (gateway)**: Local network connectivity
- **ping (8.8.8.8)**: Internet connectivity
- **dns**: DNS resolution timing
- **http**: Application layer connectivity

## Expected Duration

~30 seconds

## Privacy Considerations

Default privacy mode: **hashed**

- SSIDs and BSSIDs are SHA-256 hashed
- IP addresses are role-tagged (gateway, dns, internet)
- No URLs or hostnames logged

## Example Output

```json
{
  "pack": "wifi_troubleshoot",
  "timestamp": "2026-03-08T14:30:00Z",
  "collectors": [...],
  "runners": [...],
  "fault_domains": {
    "wifi": 0.8,
    "dns": 0.1,
    "internet": 0.1
  }
}
```

## Interpreting Results

### WiFi Issues (fault_domain.wifi > 0.7)

- Check RSSI < -70 dBm
- Check high retry rates
- Check channel congestion

### DNS Issues (fault_domain.dns > 0.7)

- Check DNS latency > 100ms
- Check DNS failures
- Try alternate DNS servers

### Internet Issues (fault_domain.internet > 0.7)

- Check gateway ping succeeds but internet fails
- Check traceroute for ISP issues
- Check HTTP timing breakdown
```

## Checklist

- [ ] Defined pack purpose and use cases
- [ ] Selected appropriate collectors
- [ ] Selected appropriate runners
- [ ] Created pack YAML in `packs/<name>.yaml`
- [ ] Tested pack execution locally
- [ ] Validated evidence output structure
- [ ] Created tests in `tests/packs/test_<name>.py`
- [ ] Documented pack in `docs/packs/<name>.md`
- [ ] Added pack to README or pack index
- [ ] All tests pass
- [ ] Pack executes in expected duration

## Common Pack Patterns

### Quick Health Check

Minimal collectors/runners for fast triage:

```yaml
name: quick_health
description: Fast connectivity check
collectors:
  - name: wifi
runners:
  - name: ping
    config:
      target: gateway
      count: 3
  - name: dns
    config:
      hostname: example.com
```

### Deep Dive

Comprehensive diagnostics for complex issues:

```yaml
name: full_diagnostic
description: Complete network analysis
collectors:
  - name: wifi
  - name: device
  - name: network
  - name: lan
runners:
  - name: ping
    config:
      target: gateway
      count: 20
  - name: ping
    config:
      target: 8.8.8.8
      count: 20
  - name: dns
    config:
      hostname: example.com
  - name: http
    config:
      url: https://www.google.com
  - name: traceroute
    config:
      target: 8.8.8.8
  - name: throughput
    config:
      duration: 10
```

### Targeted Diagnostics

Focus on specific fault domain:

```yaml
name: dns_deep_dive
description: Comprehensive DNS diagnostics
collectors:
  - name: network  # Get DNS server config
runners:
  - name: dns
    config:
      hostname: example.com
      server: auto
  - name: dns
    config:
      hostname: example.com
      server: 8.8.8.8
  - name: dns
    config:
      hostname: example.com
      server: 1.1.1.1
  - name: http
    config:
      url: https://example.com
```

### Conditional Execution

Run additional tests only if initial tests fail:

```yaml
name: escalating_diagnostic
description: Start simple, escalate if needed
runners:
  - name: ping
    config:
      target: gateway
      count: 5

  - name: traceroute
    config:
      target: gateway
    depends_on:
      - ping  # Only run if ping fails
```

## Examples

See existing packs:
- `packs/quick_health.yaml` - Fast connectivity check
- `packs/full_diagnostic.yaml` - Comprehensive analysis
- `packs/wifi_deep_dive.yaml` - WiFi-focused diagnostics
