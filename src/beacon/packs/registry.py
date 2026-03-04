"""Pack and plugin registry — maps names to concrete collector/runner classes."""

from __future__ import annotations

import logging
from pathlib import Path

from beacon.collectors.base import BaseCollector
from beacon.collectors.device import DeviceCollector
from beacon.collectors.lan import LANCollector
from beacon.collectors.wifi import WiFiCollector
from beacon.collectors.path import PathCollector
from beacon.packs.loader import PackLoader
from beacon.packs.schema import PackDefinition
from beacon.runners.base import BaseTestRunner
from beacon.runners.dns import DNSRunner
from beacon.runners.http import HTTPRunner
from beacon.runners.ping import PingRunner
from beacon.runners.throughput import ThroughputRunner
from beacon.runners.traceroute import TracerouteRunner

logger = logging.getLogger(__name__)

# Built-in plugin registrations
_COLLECTORS: dict[str, type[BaseCollector]] = {
    "device": DeviceCollector,
    "lan": LANCollector,
    "wifi": WiFiCollector,
    "path": PathCollector,
}

_RUNNERS: dict[str, type[BaseTestRunner]] = {
    "ping": PingRunner,
    "dns": DNSRunner,
    "http": HTTPRunner,
    "traceroute": TracerouteRunner,
    "throughput": ThroughputRunner,
}


class PluginRegistry:
    """Registry for collector and runner plugins."""

    def __init__(self) -> None:
        self._collectors: dict[str, type[BaseCollector]] = dict(_COLLECTORS)
        self._runners: dict[str, type[BaseTestRunner]] = dict(_RUNNERS)

    def get_collector(self, name: str) -> BaseCollector:
        cls = self._collectors.get(name)
        if cls is None:
            raise KeyError(f"Unknown collector: {name}")
        return cls()

    def get_runner(self, name: str) -> BaseTestRunner:
        cls = self._runners.get(name)
        if cls is None:
            raise KeyError(f"Unknown runner: {name}")
        return cls()

    def register_collector(self, name: str, cls: type[BaseCollector]) -> None:
        self._collectors[name] = cls

    def register_runner(self, name: str, cls: type[BaseTestRunner]) -> None:
        self._runners[name] = cls

    def list_collectors(self) -> list[str]:
        return sorted(self._collectors.keys())

    def list_runners(self) -> list[str]:
        return sorted(self._runners.keys())


class PackRegistry:
    """Registry for loaded pack definitions."""

    def __init__(self) -> None:
        self._packs: dict[str, PackDefinition] = {}

    def register(self, pack: PackDefinition) -> None:
        self._packs[pack.name] = pack

    def get(self, name: str) -> PackDefinition | None:
        return self._packs.get(name)

    def list_packs(self) -> list[PackDefinition]:
        return sorted(self._packs.values(), key=lambda p: p.name)

    def load_from_directory(self, directory: Path | str) -> int:
        """Load all packs from a directory and register them. Returns count loaded."""
        packs = PackLoader.load_directory(directory)
        for pack in packs:
            self.register(pack)
        return len(packs)
