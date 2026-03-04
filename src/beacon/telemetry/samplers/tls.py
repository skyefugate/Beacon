"""Tier 1 TLS sampler — handshake timing and certificate expiry via httpx async."""

from __future__ import annotations

import logging
import time

import httpx

from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)


class TLSSampler(BaseSampler):
    name = "tls"
    tier = 1
    default_interval = 30

    def __init__(
        self,
        targets: list[str] | None = None,
        timeout: int = 10,
    ) -> None:
        self._targets = targets or ["https://www.google.com"]
        self._timeout = timeout

    async def sample(self) -> list[Metric]:
        now = self._now()
        metrics: list[Metric] = []

        async with httpx.AsyncClient(
            timeout=self._timeout, verify=True,
        ) as client:
            for url in self._targets:
                fields = await self._probe_tls(client, url)
                if fields:
                    metrics.append(Metric(
                        measurement="t_tls_handshake",
                        fields=fields,
                        tags={"url": url},
                        timestamp=now,
                    ))

        return metrics

    async def _probe_tls(self, client: httpx.AsyncClient, url: str) -> dict:
        """Measure TLS handshake timing."""
        try:
            start = time.monotonic()
            response = await client.get(url)
            total_ms = (time.monotonic() - start) * 1000

            fields: dict = {
                "handshake_ms": round(total_ms, 2),
                "status_code": response.status_code,
                "success": True,
            }

            # Extract TLS version from the stream info if available
            stream = response.extensions.get("network_stream")
            if stream and hasattr(stream, "get_extra_info"):
                ssl_obj = stream.get_extra_info("ssl_object")
                if ssl_obj:
                    fields["tls_version"] = ssl_obj.version()

            return fields
        except httpx.TimeoutException:
            return {"success": False, "error": "timeout"}
        except Exception as e:
            logger.debug("TLS probe %s failed: %s", url, e)
            return {"success": False, "error": type(e).__name__}
