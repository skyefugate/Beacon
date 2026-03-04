"""YAML pack loader — reads and validates pack definition files."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from beacon.packs.schema import PackDefinition

logger = logging.getLogger(__name__)


class PackLoader:
    """Loads PackDefinition objects from YAML files."""

    @staticmethod
    def load_file(path: Path | str) -> PackDefinition:
        """Load a single pack from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Pack file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Pack file is empty: {path}")

        return PackDefinition.model_validate(data)

    @staticmethod
    def load_directory(directory: Path | str) -> list[PackDefinition]:
        """Load all pack YAML files from a directory."""
        directory = Path(directory)
        if not directory.is_dir():
            raise NotADirectoryError(f"Pack directory not found: {directory}")

        packs: list[PackDefinition] = []
        for path in sorted(directory.glob("*.yaml")):
            try:
                pack = PackLoader.load_file(path)
                packs.append(pack)
                logger.debug("Loaded pack %s from %s", pack.name, path)
            except Exception:
                logger.warning("Failed to load pack from %s", path, exc_info=True)

        return packs
