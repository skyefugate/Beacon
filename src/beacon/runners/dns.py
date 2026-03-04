"""Multi-resolver DNS runner — measures resolution time and detects failures."""

from __future__ import annotations

import logging
import time
from uuid import UUID

import dns.resolver

from beacon.models.envelope import Event, Metric, PluginEnvelope, Severity
from beacon.runners.base import BaseTestRunner, RunnerConfig

logger = logging.getLogger(__name__)

DEFAULT_RESOLVERS = ["8.8.8.8", "1.1.1.1", "9.9.9.9"]
DEFAULT_DOMAINS = ["google.com", "cloudflare.com"]


class DNSRunner(BaseTestRunner):
    name = "dns"
    version = "0.1.0"

    def run(self, run_id: UUID, config: RunnerConfig) -> PluginEnvelope:
        started_at = self._now()
        metrics: list[Metric] = []
        events: list[Event] = []
        notes: list[str] = []

        resolvers = config.extra.get("resolvers", DEFAULT_RESOLVERS)
        domains = config.targets or DEFAULT_DOMAINS

        for resolver_addr in resolvers:
            for domain in domains:
                now = self._now()
                try:
                    res = dns.resolver.Resolver()
                    res.nameservers = [resolver_addr]
                    res.lifetime = config.timeout_seconds

                    start = time.monotonic()
                    answers = res.resolve(domain, "A")
                    elapsed_ms = (time.monotonic() - start) * 1000

                    ips = [rdata.address for rdata in answers]

                    metrics.append(
                        Metric(
                            measurement="dns_resolve",
                            fields={
                                "latency_ms": round(elapsed_ms, 2),
                                "success": True,
                                "answer_count": len(ips),
                                "first_answer": ips[0] if ips else "",
                            },
                            tags={"resolver": resolver_addr, "domain": domain},
                            timestamp=now,
                        )
                    )

                    if elapsed_ms > 500:
                        events.append(
                            Event(
                                event_type="slow_dns",
                                severity=Severity.WARNING,
                                message=f"DNS resolution slow: {domain} via {resolver_addr} took {elapsed_ms:.0f}ms",
                                tags={"resolver": resolver_addr, "domain": domain},
                                timestamp=now,
                            )
                        )

                except dns.resolver.NXDOMAIN:
                    metrics.append(
                        Metric(
                            measurement="dns_resolve",
                            fields={"success": False, "error": "NXDOMAIN"},
                            tags={"resolver": resolver_addr, "domain": domain},
                            timestamp=now,
                        )
                    )
                    events.append(
                        Event(
                            event_type="dns_failure",
                            severity=Severity.CRITICAL,
                            message=f"NXDOMAIN: {domain} via {resolver_addr}",
                            tags={"resolver": resolver_addr, "domain": domain},
                            timestamp=now,
                        )
                    )

                except dns.resolver.NoNameservers:
                    metrics.append(
                        Metric(
                            measurement="dns_resolve",
                            fields={"success": False, "error": "no_nameservers"},
                            tags={"resolver": resolver_addr, "domain": domain},
                            timestamp=now,
                        )
                    )
                    events.append(
                        Event(
                            event_type="dns_failure",
                            severity=Severity.CRITICAL,
                            message=f"No nameservers available for {domain} via {resolver_addr}",
                            tags={"resolver": resolver_addr, "domain": domain},
                            timestamp=now,
                        )
                    )

                except dns.exception.Timeout:
                    metrics.append(
                        Metric(
                            measurement="dns_resolve",
                            fields={"success": False, "error": "timeout"},
                            tags={"resolver": resolver_addr, "domain": domain},
                            timestamp=now,
                        )
                    )
                    events.append(
                        Event(
                            event_type="dns_timeout",
                            severity=Severity.CRITICAL,
                            message=f"DNS timeout: {domain} via {resolver_addr}",
                            tags={"resolver": resolver_addr, "domain": domain},
                            timestamp=now,
                        )
                    )

                except Exception as e:
                    notes.append(f"DNS query failed for {domain} via {resolver_addr}: {e}")

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
