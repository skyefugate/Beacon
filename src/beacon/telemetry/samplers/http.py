"""HTTP telemetry sampler — measures response timing via httpx async."""

from __future__ import annotations

import logging
import time

import httpx

from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)


class HTTPSampler(BaseSampler):
    name = "http"
    tier = 0
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
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            for url in self._targets:
                fields = await self._probe(client, url)
                metrics.append(
                    Metric(
                        measurement="t_http_timing",
                        fields=fields,
                        tags={"url": url, "method": "GET"},
                        timestamp=now,
                    )
                )

        return metrics

    async def _probe(self, client: httpx.AsyncClient, url: str) -> dict:
        """Issue a GET and record timing."""
        try:
            start = time.monotonic()
            response = await client.get(url)
            total_ms = (time.monotonic() - start) * 1000

            return {
                "status_code": response.status_code,
                "total_ms": round(total_ms, 2),
                "response_ms": round(response.elapsed.total_seconds() * 1000, 2),
                "content_length": len(response.content),
                "success": 200 <= response.status_code < 400,
            }
        except httpx.TimeoutException:
            return {"success": False, "error": "timeout"}
        except httpx.ConnectError:
            return {"success": False, "error": "connect_error"}
        except Exception as e:
            logger.debug("HTTP probe %s failed: %s", url, e)
            return {"success": False, "error": str(type(e).__name__)}
