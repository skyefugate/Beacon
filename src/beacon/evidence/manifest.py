"""Artifact manifest builder — collects all artifacts from envelopes."""

from __future__ import annotations

from beacon.models.envelope import Artifact, PluginEnvelope


def build_manifest(envelopes: list[PluginEnvelope]) -> list[Artifact]:
    """Collect all unique artifacts from a set of plugin envelopes.

    Deduplicates by SHA-256 hash.
    """
    seen: set[str] = set()
    manifest: list[Artifact] = []

    for envelope in envelopes:
        for artifact in envelope.artifacts:
            if artifact.sha256 not in seen:
                seen.add(artifact.sha256)
                manifest.append(artifact)

    return manifest
