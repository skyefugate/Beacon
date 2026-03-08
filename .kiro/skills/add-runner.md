---
name: add-runner
description: Add a new active network test runner to Beacon for performing diagnostic checks
---

# Add Runner Skill

Use this skill when adding a new **active test runner** to Beacon.

Runners perform active network tests that generate traffic.

## When to Use

- Adding ping/latency tests
- Adding DNS resolution checks
- Adding HTTP/HTTPS endpoint tests
- Adding traceroute functionality
- Adding throughput measurements

## When NOT to Use

- For passive observation → use `add-collector` skill instead
- For diagnostic pack creation → use `create-diagnostic-pack` skill

## Steps

### 1. Create Runner Module

Create `src/beacon/runners/<name>.py`:

```python
"""<Name> runner for Beacon."""

from typing import Optional
from pydantic import BaseModel, Field
from beacon.runners.base import BaseRunner, RunnerResult, runner_registry


class <Name>Config(BaseModel):
    """Configuration for <name> runner."""
    target: str = Field(..., description="Target host/URL")
    timeout: int = Field(10, ge=1, le=300, description="Timeout in seconds")
    # Add runner-specific config fields


class <Name>Result(BaseModel):
    """Result from <name> test."""
    target: str = Field(..., description="Target tested")
    success: bool = Field(..., description="Test succeeded")
    latency_ms: Optional[float] = Field(None, description="Latency in milliseconds")
    error: Optional[str] = Field(None, description="Error message if failed")
    # Add runner-specific result fields


class <Name>Runner(BaseRunner):
    """Run <description> test."""

    def __init__(self, config: <Name>Config):
        super().__init__(config)
        self.config = config

    async def run(self) -> RunnerResult:
        """
        Execute <name> test.

        Returns:
            RunnerResult with test outcome and timing data
        """
        start_time = time.time()

        try:
            # Implement test logic
            result = await self._execute_test()

            return RunnerResult(
                success=True,
                runner="<name>",
                data=<Name>Result(
                    target=self.config.target,
                    success=True,
                    latency_ms=(time.time() - start_time) * 1000,
                    **result
                ),
                duration_ms=(time.time() - start_time) * 1000
            )
        except TimeoutError:
            return RunnerResult(
                success=False,
                runner="<name>",
                error=f"Timeout after {self.config.timeout}s",
                duration_ms=(time.time() - start_time) * 1000
            )
        except Exception as e:
            return RunnerResult(
                success=False,
                runner="<name>",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000
            )

    async def _execute_test(self) -> dict:
        """Platform-specific test execution."""
        # Implement actual test logic
        pass


# Register runner
@runner_registry.register("<name>")
def create_<name>_runner(config: dict) -> <Name>Runner:
    """Factory function for <name> runner."""
    return <Name>Runner(<Name>Config(**config))
```

### 2. Handle Privileged Operations

If runner requires raw sockets or elevated privileges:

```python
import socket

class PrivilegedRunner(BaseRunner):
    """Runner requiring elevated privileges."""

    def __init__(self, config):
        super().__init__(config)
        self._check_privileges()

    def _check_privileges(self):
        """Verify runner has required privileges."""
        try:
            # Try to create raw socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            sock.close()
        except PermissionError:
            raise RuntimeError(
                f"{self.__class__.__name__} requires root privileges or CAP_NET_RAW"
            )
```

### 3. Implement Timeout Handling

```python
import asyncio

async def _execute_with_timeout(self) -> dict:
    """Execute test with timeout."""
    try:
        return await asyncio.wait_for(
            self._execute_test(),
            timeout=self.config.timeout
        )
    except asyncio.TimeoutError:
        raise TimeoutError(f"Test timed out after {self.config.timeout}s")
```

### 4. Create Tests

Create `tests/runners/test_<name>.py`:

```python
"""Tests for <name> runner."""

import pytest
from beacon.runners.<name> import <Name>Runner, <Name>Config


class Test<Name>Runner:
    """Tests for <Name>Runner."""

    @pytest.mark.asyncio
    async def test_run_success(self, mock_<dependency>):
        """Should execute test successfully."""
        config = <Name>Config(target="example.com", timeout=10)
        runner = <Name>Runner(config)

        result = await runner.run()

        assert result.success is True
        assert result.data.target == "example.com"
        assert result.data.latency_ms > 0

    @pytest.mark.asyncio
    async def test_run_timeout(self, mock_<dependency>_timeout):
        """Should return error on timeout."""
        config = <Name>Config(target="example.com", timeout=1)
        runner = <Name>Runner(config)

        result = await runner.run()

        assert result.success is False
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_run_failure(self, mock_<dependency>_failure):
        """Should return error on test failure."""
        config = <Name>Config(target="nonexistent.invalid", timeout=10)
        runner = <Name>Runner(config)

        result = await runner.run()

        assert result.success is False
        assert result.error is not None

    @pytest.mark.parametrize("target,expected_success", [
        ("example.com", True),
        ("192.168.1.1", True),
        ("invalid..domain", False),
    ])
    @pytest.mark.asyncio
    async def test_run_various_targets(self, target, expected_success, mock_<dependency>):
        """Should handle various target formats."""
        config = <Name>Config(target=target, timeout=10)
        runner = <Name>Runner(config)

        result = await runner.run()

        assert result.success == expected_success


@pytest.fixture
def mock_<dependency>(monkeypatch):
    """Mock external dependency for testing."""
    async def fake_test(*args, **kwargs):
        return {"latency_ms": 42.0}
    monkeypatch.setattr("beacon.runners.<name>._execute_test", fake_test)
```

### 5. Add to Pack Definitions

Update pack YAML files in `packs/` to include new runner:

```yaml
name: example_pack
description: Example diagnostic pack
collectors:
  # ... existing collectors
runners:
  - name: <name>
    config:
      target: example.com
      timeout: 10
```

### 6. Update Documentation

Add runner to `docs/runners.md` (create if doesn't exist):

```markdown
## <Name> Runner

**Purpose**: Test <description>

**Privileges**: Root/CAP_NET_RAW required (or "None required")

**Configuration**:
```yaml
runners:
  - name: <name>
    config:
      target: example.com  # Target host/URL
      timeout: 10          # Timeout in seconds
```

**Results**:
- `latency_ms`: Round-trip latency
- `success`: Test outcome
- Additional metrics...

**Example Output**:
```json
{
  "success": true,
  "target": "example.com",
  "latency_ms": 42.5
}
```
```

### 7. Run Tests and Linting

```bash
# Run tests
pytest tests/runners/test_<name>.py -v

# Run linting
ruff check src/beacon/runners/<name>.py

# Run type checking
mypy src/beacon/runners/<name>.py

# Or use pre-commit
pre-commit run --files src/beacon/runners/<name>.py tests/runners/test_<name>.py
```

## Checklist

- [ ] Created runner module in `src/beacon/runners/<name>.py`
- [ ] Inherited from `BaseRunner`
- [ ] Implemented `run()` method returning `RunnerResult`
- [ ] Registered with `@runner_registry.register("<name>")`
- [ ] Created Pydantic models for config and results
- [ ] Implemented timeout handling
- [ ] Handled privilege requirements (if applicable)
- [ ] Created tests in `tests/runners/test_<name>.py`
- [ ] Added mocks for network operations
- [ ] Tested success, timeout, and failure paths
- [ ] Used parametrized tests for multiple scenarios
- [ ] Updated pack definitions to use new runner
- [ ] Added documentation
- [ ] All tests pass
- [ ] Linting passes
- [ ] Type checking passes

## Common Patterns

### DNS Resolution

```python
import socket

async def _resolve_dns(self, hostname: str) -> str:
    """Resolve hostname to IP address."""
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror as e:
        raise RuntimeError(f"DNS resolution failed: {e}")
```

### HTTP Request with Timing

```python
import aiohttp

async def _http_request(self, url: str) -> dict:
    """Make HTTP request and measure timing."""
    start = time.time()

    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=self.config.timeout) as response:
            dns_time = time.time() - start
            await response.read()
            total_time = time.time() - start

            return {
                "status_code": response.status,
                "dns_ms": dns_time * 1000,
                "total_ms": total_time * 1000
            }
```

### ICMP Ping (Privileged)

```python
import socket
import struct

def _send_icmp_ping(self, target_ip: str) -> float:
    """Send ICMP echo request and measure RTT."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    sock.settimeout(self.config.timeout)

    # Build ICMP packet
    packet = struct.pack("!BBHHH", 8, 0, 0, 1, 1)  # Type, Code, Checksum, ID, Seq
    checksum = self._calculate_checksum(packet)
    packet = struct.pack("!BBHHH", 8, 0, checksum, 1, 1)

    start = time.time()
    sock.sendto(packet, (target_ip, 0))

    # Wait for reply
    data, addr = sock.recvfrom(1024)
    rtt = (time.time() - start) * 1000

    sock.close()
    return rtt
```

### Retry Logic

```python
async def _execute_with_retry(self, max_retries: int = 3) -> dict:
    """Execute test with retry on transient failures."""
    last_error = None

    for attempt in range(max_retries):
        try:
            return await self._execute_test()
        except TransientError as e:
            last_error = e
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

    raise RuntimeError(f"Failed after {max_retries} attempts: {last_error}")
```

## Examples

See existing runners:
- `src/beacon/runners/ping.py` - ICMP/TCP ping
- `src/beacon/runners/dns.py` - DNS resolution
- `src/beacon/runners/http.py` - HTTP/HTTPS requests
- `src/beacon/runners/traceroute.py` - Network path tracing
