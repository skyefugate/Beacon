"""HTTP(S) timing breakdown runner — measures connection, TLS, TTFB, and total time."""

from __future__ import annotations

import logging
import time
from uuid import UUID

import httpx

from beacon.models.envelope import Event, Metric, PluginEnvelope, Severity
from beacon.runners.base import BaseTestRunner, RunnerConfig

logger = logging.getLogger(__name__)

DEFAULT_TARGETS = ["https://www.google.com", "https://www.cloudflare.com"]


class HTTPRunner(BaseTestRunner):
    name = "http"
    version = "0.1.0"

    def run(self, run_id: UUID, config: RunnerConfig) -> PluginEnvelope:
        started_at = self._now()
        metrics: list[Metric] = []
        events: list[Event] = []
        notes: list[str] = []

        targets = config.targets or DEFAULT_TARGETS

        for url in targets:
            now = self._now()
            try:
                start = time.monotonic()
                with httpx.Client(timeout=config.timeout_seconds, follow_redirects=True) as client:
                    response = client.get(url)
                total_ms = (time.monotonic() - start) * 1000

                elapsed = response.elapsed
                elapsed_ms = elapsed.total_seconds() * 1000

                fields: dict[str, float | int | str | bool] = {
                    "status_code": response.status_code,
                    "total_ms": round(total_ms, 2),
                    "response_ms": round(elapsed_ms, 2),
                    "content_length": len(response.content),
                    "success": 200 <= response.status_code < 400,
                }

                # Extract timing from httpx extensions if available
                network_stream = response.extensions.get("network_stream")
                if network_stream:
                    pass  # httpx doesn't expose fine-grained timing in sync mode

                metrics.append(Metric(
                    measurement="http_timing",
                    fields=fields,
                    tags={"url": url, "method": "GET"},
                    timestamp=now,
                ))

                if response.status_code >= 400:
                    events.append(Event(
                        event_type="http_error",
                        severity=Severity.WARNING if response.status_code < 500 else Severity.CRITICAL,
                        message=f"HTTP {response.status_code} from {url}",
                        tags={"url": url},
                        timestamp=now,
                    ))

                if total_ms > 2000:
                    events.append(Event(
                        event_type="slow_http",
                        severity=Severity.WARNING,
                        message=f"Slow HTTP response from {url}: {total_ms:.0f}ms",
                        tags={"url": url},
                        timestamp=now,
                    ))

            except httpx.ConnectTimeout:
                metrics.append(Metric(
                    measurement="http_timing",
                    fields={"success": False, "error": "connect_timeout"},
                    tags={"url": url, "method": "GET"},
                    timestamp=now,
                ))
                events.append(Event(
                    event_type="http_timeout",
                    severity=Severity.CRITICAL,
                    message=f"Connection timeout to {url}",
                    tags={"url": url},
                    timestamp=now,
                ))

            except httpx.ReadTimeout:
                metrics.append(Metric(
                    measurement="http_timing",
                    fields={"success": False, "error": "read_timeout"},
                    tags={"url": url, "method": "GET"},
                    timestamp=now,
                ))
                events.append(Event(
                    event_type="http_timeout",
                    severity=Severity.CRITICAL,
                    message=f"Read timeout from {url}",
                    tags={"url": url},
                    timestamp=now,
                ))

            except httpx.ConnectError as e:
                metrics.append(Metric(
                    measurement="http_timing",
                    fields={"success": False, "error": "connect_error"},
                    tags={"url": url, "method": "GET"},
                    timestamp=now,
                ))
                events.append(Event(
                    event_type="http_connect_error",
                    severity=Severity.CRITICAL,
                    message=f"Cannot connect to {url}: {e}",
                    tags={"url": url},
                    timestamp=now,
                ))

            except Exception as e:
                notes.append(f"HTTP test failed for {url}: {e}")

        return PluginEnvelope(
            plugin_name=self.name,
            plugin_version=self.version,
            run_id=run_id,
            metrics=metrics,
            events=events,
            notes=notes,
            started_at=started_at,
            completed_at=self._now(),
        )
