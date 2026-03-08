---
name: add-collector
description: Add a new passive data collector to Beacon for observing network or system state
---

# Add Collector Skill

Use this skill when adding a new **passive data collector** to Beacon.

Collectors observe system or network state without generating traffic.

## When to Use

- Adding WiFi metrics collection
- Adding device health monitoring (CPU, memory, battery)
- Adding network topology discovery (ARP, LLDP)
- Adding interface configuration collection

## When NOT to Use

- For active network tests → use `add-runner` skill instead
- For diagnostic pack creation → use `create-diagnostic-pack` skill

## Steps

### 1. Create Collector Module

Create `src/beacon/collectors/<name>.py`:

```python
"""<Name> collector for Beacon."""

from typing import Optional
from pydantic import BaseModel, Field
from beacon.collectors.base import BaseCollector, CollectorResult, collector_registry


class <Name>Data(BaseModel):
    """Data collected by <Name> collector."""
    # Add fields for collected data
    metric_name: float = Field(..., description="Description of metric")
    timestamp: float = Field(..., description="Collection timestamp")


class <Name>Collector(BaseCollector):
    """Collect <description> metrics."""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        # Initialize collector-specific state

    async def collect(self) -> CollectorResult:
        """
        Collect <name> metrics.

        Returns:
            CollectorResult with success status and data or error
        """
        try:
            # Implement collection logic
            data = self._collect_data()

            return CollectorResult(
                success=True,
                collector="<name>",
                data=<Name>Data(**data),
                timestamp=time.time()
            )
        except Exception as e:
            return CollectorResult(
                success=False,
                collector="<name>",
                error=str(e),
                timestamp=time.time()
            )

    def _collect_data(self) -> dict:
        """Platform-specific collection logic."""
        # Implement actual collection
        pass


# Register collector
@collector_registry.register("<name>")
def create_<name>_collector(config: Optional[dict] = None) -> <Name>Collector:
    """Factory function for <name> collector."""
    return <Name>Collector(config)
```

### 2. Handle Platform Differences

If collector is platform-specific, create separate implementations:

```python
import sys
from beacon.collectors.base import BaseCollector

if sys.platform == "darwin":
    from beacon.collectors.<name>_macos import MacOS<Name>Collector as <Name>Collector
elif sys.platform == "linux":
    from beacon.collectors.<name>_linux import Linux<Name>Collector as <Name>Collector
else:
    # Fallback for unsupported platforms
    class <Name>Collector(BaseCollector):
        async def collect(self):
            return CollectorResult(
                success=False,
                collector="<name>",
                error=f"Platform {sys.platform} not supported"
            )
```

### 3. Create Tests

Create `tests/collectors/test_<name>.py`:

```python
"""Tests for <name> collector."""

import pytest
from beacon.collectors.<name> import <Name>Collector, <Name>Data


class Test<Name>Collector:
    """Tests for <Name>Collector."""

    def test_collect_success(self, mock_<dependency>):
        """Should collect <name> metrics successfully."""
        collector = <Name>Collector()
        result = await collector.collect()

        assert result.success is True
        assert isinstance(result.data, <Name>Data)
        assert result.data.metric_name > 0

    def test_collect_failure(self, mock_<dependency>_failure):
        """Should return error on collection failure."""
        collector = <Name>Collector()
        result = await collector.collect()

        assert result.success is False
        assert result.error is not None

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
    def test_collect_real_macos(self):
        """Integration test with real system on macOS."""
        collector = <Name>Collector()
        result = await collector.collect()
        # Don't assert success (may fail on CI), just check structure
        assert hasattr(result, "success")


@pytest.fixture
def mock_<dependency>(monkeypatch):
    """Mock external dependency for testing."""
    def fake_call(*args, **kwargs):
        return {"metric_name": 42.0}
    monkeypatch.setattr("beacon.collectors.<name>._collect_data", fake_call)
```

### 4. Add to Pack Definitions

Update pack YAML files in `packs/` to include new collector:

```yaml
name: example_pack
description: Example diagnostic pack
collectors:
  - name: <name>
    config:
      # Optional collector-specific config
runners:
  # ... existing runners
```

### 5. Update Documentation

Add collector to `docs/collectors.md` (create if doesn't exist):

```markdown
## <Name> Collector

**Purpose**: Collect <description>

**Platforms**: macOS, Linux (or specify limitations)

**Metrics**:
- `metric_name`: Description of what this measures

**Configuration**:
```yaml
collectors:
  - name: <name>
    config:
      option: value
```

**Privacy**: Describe what identifiers are collected and how they're handled
```

### 6. Run Tests and Linting

```bash
# Run tests
pytest tests/collectors/test_<name>.py -v

# Run linting
ruff check src/beacon/collectors/<name>.py

# Run type checking
mypy src/beacon/collectors/<name>.py

# Or use pre-commit to run all checks
pre-commit run --files src/beacon/collectors/<name>.py tests/collectors/test_<name>.py
```

## Checklist

- [ ] Created collector module in `src/beacon/collectors/<name>.py`
- [ ] Inherited from `BaseCollector`
- [ ] Implemented `collect()` method returning `CollectorResult`
- [ ] Registered with `@collector_registry.register("<name>")`
- [ ] Created Pydantic model for collected data
- [ ] Handled platform differences (if applicable)
- [ ] Created tests in `tests/collectors/test_<name>.py`
- [ ] Added mocks for external dependencies
- [ ] Tested both success and failure paths
- [ ] Updated pack definitions to use new collector
- [ ] Added documentation
- [ ] All tests pass
- [ ] Linting passes
- [ ] Type checking passes

## Common Patterns

### Subprocess Execution

```python
import subprocess

def _run_command(self, cmd: list[str]) -> str:
    """Run system command and return output."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {result.stderr}")
    return result.stdout
```

### Privacy-Aware Collection

```python
from beacon.models.privacy import hash_identifier

def _collect_wifi_data(self) -> dict:
    """Collect WiFi data with privacy hashing."""
    ssid = get_current_ssid()
    bssid = get_current_bssid()

    return {
        "ssid_hash": hash_identifier(ssid, self.config.privacy_mode),
        "bssid_hash": hash_identifier(bssid, self.config.privacy_mode),
        "rssi": get_rssi()
    }
```

### Graceful Degradation

```python
def _collect_optional_metric(self) -> Optional[float]:
    """Collect metric that may not be available."""
    try:
        return get_metric()
    except (FileNotFoundError, PermissionError):
        # Metric not available on this platform/config
        return None
```

## Examples

See existing collectors:
- `src/beacon/collectors/wifi.py` - WiFi signal quality
- `src/beacon/collectors/device.py` - Device health metrics
- `src/beacon/collectors/network.py` - Network interface info
