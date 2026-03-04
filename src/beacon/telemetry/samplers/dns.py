"""DNS telemetry sampler — measures resolution latency using dnspython."""

from __future__ import annotations

import asyncio
import logging
import time

import dns.resolver

from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)


class DNSSampler(BaseSampler):
    name = "dns"
    tier = 0
    default_interval = 30

    def __init__(
        self,
        resolvers: list[str] | None = None,
        domains: list[str] | None = None,
        timeout: int = 5,
    ) -> None:
        self._resolvers = resolvers or ["8.8.8.8"]
        self._domains = domains or ["google.com"]
        self._timeout = timeout

    async def sample(self) -> list[Metric]:
        now = self._now()
        metrics: list[Metric] = []

        for resolver_addr in self._resolvers:
            for domain in self._domains:
                fields = await asyncio.to_thread(
                    self._resolve,
                    resolver_addr,
                    domain,
                )
                metrics.append(
                    Metric(
                        measurement="t_dns_latency",
                        fields=fields,
                        tags={"resolver": resolver_addr, "domain": domain},
                        timestamp=now,
                    )
                )

        return metrics

    def _resolve(self, resolver_addr: str, domain: str) -> dict:
        """Synchronous DNS resolve (runs in thread executor)."""
        try:
            res = dns.resolver.Resolver()
            res.nameservers = [resolver_addr]
            res.lifetime = self._timeout

            start = time.monotonic()
            answers = res.resolve(domain, "A")
            elapsed_ms = (time.monotonic() - start) * 1000

            return {
                "latency_ms": round(elapsed_ms, 2),
                "success": True,
                "answer_count": len(list(answers)),
            }
        except Exception as e:
            logger.debug("DNS resolve %s via %s failed: %s", domain, resolver_addr, e)
            return {"latency_ms": 0.0, "success": False, "error": type(e).__name__}
