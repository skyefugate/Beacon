"""Per-NIC network interface traffic sampler.

Collects bytes sent/received, packet counts, errors, and drops per network
interface using psutil.net_io_counters(pernic=True). Rates are computed as
deltas between successive samples.
"""

from __future__ import annotations

import asyncio
import logging
import time

import psutil

from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)

# Interfaces to skip by default (loopback)
_LOOPBACK_INTERFACES = {"lo", "lo0"}


class NicSampler(BaseSampler):
    """Per-NIC traffic sampler tracking bytes, packets, errors and drops."""

    name = "nic"
    tier = 0
    default_interval = 30

    def __init__(self, skip_loopback: bool = True) -> None:
        self._skip_loopback = skip_loopback
        # State: {nic_name: (timestamp, snetio_counters)}
        self._prev: dict = {}

    async def sample(self) -> list[Metric]:
        now = self._now()
        try:
            counters, ts = await asyncio.to_thread(self._collect)
        except Exception as e:
            logger.debug("NIC sample failed: %s", e)
            return []

        metrics: list[Metric] = []

        for nic_name, current in counters.items():
            if self._skip_loopback and nic_name in _LOOPBACK_INTERFACES:
                continue

            prev_entry = self._prev.get(nic_name)

            if prev_entry is not None:
                prev_ts, prev_counters = prev_entry
                elapsed = ts - prev_ts

                if elapsed > 0:
                    fields = self._compute_fields(current, prev_counters, elapsed)
                    metrics.append(
                        Metric(
                            measurement="t_nic_traffic",
                            fields=fields,
                            tags={"interface": nic_name},
                            timestamp=now,
                        )
                    )

            # Update state for next sample
            self._prev[nic_name] = (ts, current)

        # Remove state for interfaces that have disappeared
        disappeared = set(self._prev) - set(counters)
        for nic_name in disappeared:
            del self._prev[nic_name]

        return metrics

    @staticmethod
    def _collect():
        """Synchronous psutil call -- runs in thread executor."""
        counters = psutil.net_io_counters(pernic=True)
        ts = time.monotonic()
        return counters, ts

    @staticmethod
    def _compute_fields(current, prev, elapsed: float) -> dict:
        """Compute rate and cumulative delta fields between two counter snapshots."""
        bytes_sent_delta = max(0, current.bytes_sent - prev.bytes_sent)
        bytes_recv_delta = max(0, current.bytes_recv - prev.bytes_recv)
        packets_sent_delta = max(0, current.packets_sent - prev.packets_sent)
        packets_recv_delta = max(0, current.packets_recv - prev.packets_recv)
        errin_delta = max(0, current.errin - prev.errin)
        errout_delta = max(0, current.errout - prev.errout)
        dropin_delta = max(0, current.dropin - prev.dropin)
        dropout_delta = max(0, current.dropout - prev.dropout)

        return {
            # Rates (per second)
            "bytes_sent_rate": round(bytes_sent_delta / elapsed, 2),
            "bytes_recv_rate": round(bytes_recv_delta / elapsed, 2),
            "packets_sent_rate": round(packets_sent_delta / elapsed, 2),
            "packets_recv_rate": round(packets_recv_delta / elapsed, 2),
            # Deltas over the sampling interval
            "bytes_sent": bytes_sent_delta,
            "bytes_recv": bytes_recv_delta,
            "packets_sent": packets_sent_delta,
            "packets_recv": packets_recv_delta,
            "errors_in": errin_delta,
            "errors_out": errout_delta,
            "drops_in": dropin_delta,
            "drops_out": dropout_delta,
        }
