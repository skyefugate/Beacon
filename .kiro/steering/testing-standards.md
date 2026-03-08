---
mode: always
---

# Testing Standards — Beacon

## Test Requirements

All code changes must include tests. No exceptions.

### Coverage Targets

- **Overall**: >80% line coverage
- **Core modules**: >90% coverage
  - `src/beacon/telemetry/`
  - `src/beacon/packs/`
  - `src/beacon/storage/`
- **Collectors/Runners**: >70% coverage (platform-specific code may be untestable)

### Test Types

1. **Unit tests**: Test individual functions/classes in isolation
2. **Integration tests**: Test component interactions
3. **Platform tests**: Test platform-specific code (macOS, Linux)

## Test Structure

### Directory Layout

Mirror source structure:

```
src/beacon/collectors/wifi.py  →  tests/collectors/test_wifi.py
src/beacon/runners/ping.py     →  tests/runners/test_ping.py
src/beacon/telemetry/scheduler.py → tests/telemetry/test_scheduler.py
```

### File Naming

- Test files: `test_<module>.py`
- Test functions: `test_<function_name>_<scenario>()`
- Test classes: `Test<ClassName>`

### Test Organization

```python
# tests/collectors/test_wifi.py

import pytest
from beacon.collectors.wifi import WiFiCollector

class TestWiFiCollector:
    """Tests for WiFiCollector."""

    def test_collect_success(self, mock_system_profiler):
        """Should parse WiFi metrics from system_profiler output."""
        # Arrange
        collector = WiFiCollector()
        mock_system_profiler.return_value = SAMPLE_OUTPUT

        # Act
        result = collector.collect()

        # Assert
        assert result.success is True
        assert result.data.rssi == -45
        assert result.data.ssid_hash.startswith("sha256:")

    def test_collect_no_wifi_interface(self, mock_system_profiler):
        """Should return error when no WiFi interface found."""
        # Arrange
        collector = WiFiCollector()
        mock_system_profiler.return_value = ""

        # Act
        result = collector.collect()

        # Assert
        assert result.success is False
        assert "no wifi interface" in result.error.lower()

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
    def test_collect_real_system(self):
        """Integration test with real system_profiler."""
        collector = WiFiCollector()
        result = collector.collect()
        # Don't assert success (may not have WiFi), just check structure
        assert hasattr(result, "success")
```

## Mocking Strategy

### What to Mock

- **External commands**: `subprocess.run()`, `os.system()`
- **Network calls**: HTTP requests, DNS queries, ping
- **System APIs**: Platform-specific calls
- **Time**: `time.time()`, `datetime.now()`
- **InfluxDB**: Database writes

### What NOT to Mock

- **Pydantic models**: Test real validation
- **Pure functions**: Test actual logic
- **Internal helpers**: Test real implementations

### Mock Examples

```python
# Mock subprocess calls
@pytest.fixture
def mock_system_profiler(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=SAMPLE_WIFI_OUTPUT,
            stderr=""
        )
    monkeypatch.setattr("subprocess.run", fake_run)
    return fake_run

# Mock InfluxDB
@pytest.fixture
def mock_influxdb():
    with patch("beacon.storage.influxdb.InfluxDBClient") as mock:
        mock.return_value.write_api.return_value.write.return_value = None
        yield mock

# Mock time
@pytest.fixture
def frozen_time(monkeypatch):
    fake_time = 1234567890.0
    monkeypatch.setattr("time.time", lambda: fake_time)
    return fake_time
```

## Fixtures

### Common Fixtures

Place in `tests/conftest.py`:

```python
@pytest.fixture
def sample_config():
    """Minimal valid config for testing."""
    return BeaconConfig(
        device_id="test-device",
        influxdb_url="http://localhost:8086",
        influxdb_token="test-token",
        privacy_mode="hashed"
    )

@pytest.fixture
def temp_evidence_dir(tmp_path):
    """Temporary directory for evidence packs."""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    return evidence_dir
```

### Fixture Scope

- **function** (default): New instance per test
- **class**: Shared across test class
- **module**: Shared across test file
- **session**: Shared across entire test run

Use broader scopes for expensive setup (database connections, large data files).

## Async Testing

Use `pytest-asyncio` for async code:

```python
import pytest

@pytest.mark.asyncio
async def test_telemetry_scheduler():
    """Should schedule samplers at correct intervals."""
    scheduler = TelemetryScheduler()
    await scheduler.start()

    # Wait for first sample
    await asyncio.sleep(1.1)

    assert scheduler.sample_count > 0
    await scheduler.stop()
```

## Parametrized Tests

Test multiple scenarios efficiently:

```python
@pytest.mark.parametrize("rssi,expected_quality", [
    (-30, "excellent"),
    (-50, "good"),
    (-70, "fair"),
    (-90, "poor"),
])
def test_wifi_quality_classification(rssi, expected_quality):
    """Should classify WiFi quality based on RSSI."""
    quality = classify_wifi_quality(rssi)
    assert quality == expected_quality
```

## Platform-Specific Tests

```python
@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_macos_wifi_collector():
    """Test macOS-specific WiFi collection."""
    collector = MacOSWiFiCollector()
    result = collector.collect()
    assert result.success

@pytest.mark.skipif(sys.platform != "linux", reason="Linux only")
def test_linux_wifi_collector():
    """Test Linux-specific WiFi collection."""
    collector = LinuxWiFiCollector()
    result = collector.collect()
    assert result.success
```

## Integration Tests

Place in `tests/integration/`:

```python
# tests/integration/test_pack_execution.py

@pytest.mark.integration
def test_full_diagnostic_pack(sample_config, temp_evidence_dir):
    """Should execute full diagnostic pack end-to-end."""
    pack = load_pack("full_diagnostic.yaml")
    executor = PackExecutor(config=sample_config)

    result = executor.run(pack)

    assert result.success
    assert len(result.evidence.collectors) > 0
    assert len(result.evidence.runners) > 0

    # Check evidence file created
    evidence_files = list(temp_evidence_dir.glob("*.json"))
    assert len(evidence_files) == 1
```

Run integration tests separately:

```bash
pytest tests/integration/ -m integration
```

## Test Data

### Sample Data Files

Place in `tests/fixtures/`:

```
tests/fixtures/
├── wifi_output_macos.txt
├── wifi_output_linux.txt
├── dns_response.json
└── http_timing.json
```

Load in tests:

```python
def load_fixture(filename):
    fixture_path = Path(__file__).parent / "fixtures" / filename
    return fixture_path.read_text()

def test_parse_wifi_output():
    output = load_fixture("wifi_output_macos.txt")
    result = parse_wifi_output(output)
    assert result.rssi == -45
```

## Error Testing

Test both success and failure paths:

```python
def test_dns_runner_success(mock_dns):
    """Should return DNS timing on successful query."""
    runner = DNSRunner(target="example.com")
    result = runner.run()
    assert result.success
    assert result.latency_ms > 0

def test_dns_runner_timeout(mock_dns_timeout):
    """Should return error on DNS timeout."""
    runner = DNSRunner(target="example.com", timeout=1)
    result = runner.run()
    assert result.success is False
    assert "timeout" in result.error.lower()

def test_dns_runner_nxdomain(mock_dns_nxdomain):
    """Should return error on NXDOMAIN."""
    runner = DNSRunner(target="nonexistent.invalid")
    result = runner.run()
    assert result.success is False
    assert "nxdomain" in result.error.lower()
```

## Performance Testing

Use `pytest-benchmark` for performance-critical code:

```python
def test_telemetry_aggregation_performance(benchmark):
    """Should aggregate 1000 samples in <100ms."""
    samples = generate_sample_data(1000)
    aggregator = TelemetryAggregator()

    result = benchmark(aggregator.aggregate, samples)

    assert len(result) > 0
    assert benchmark.stats.mean < 0.1  # <100ms
```

## Test Execution

### Run All Tests

```bash
pytest tests/
```

### Run Specific Tests

```bash
# Single file
pytest tests/collectors/test_wifi.py

# Single test
pytest tests/collectors/test_wifi.py::test_collect_success

# By marker
pytest -m "not integration"
```

### Coverage Report

```bash
pytest --cov=src/beacon --cov-report=html tests/
open htmlcov/index.html
```

### Fail Fast

```bash
pytest -x  # Stop on first failure
pytest --maxfail=3  # Stop after 3 failures
```

## CI Integration

Tests run automatically on:
- Every commit (via pre-commit hook)
- Every push (via GitHub Actions)
- Every pull request

CI must pass before merge.

## Test Maintenance

### When to Update Tests

- **Code changes**: Update tests to match new behavior
- **Bug fixes**: Add regression test before fixing
- **Refactoring**: Tests should still pass (if behavior unchanged)

### Flaky Tests

If a test fails intermittently:
1. Add `@pytest.mark.flaky(reruns=3)` temporarily
2. Investigate root cause (timing, race condition, external dependency)
3. Fix properly (better mocking, explicit waits, deterministic data)
4. Remove flaky marker

### Slow Tests

If tests take >5 seconds:
1. Mark with `@pytest.mark.slow`
2. Consider moving to integration tests
3. Optimize setup/teardown
4. Use broader fixture scopes

## Documentation

Every test should have a docstring explaining:
- **What** is being tested
- **Why** it matters (if not obvious)
- **How** to interpret failures

```python
def test_wifi_roaming_correlation():
    """
    Should correlate WiFi roaming events with latency spikes.

    This tests the core fault domain analysis logic. If this fails,
    the system may incorrectly blame DNS/ISP for WiFi roaming issues.
    """
    # Test implementation
```
