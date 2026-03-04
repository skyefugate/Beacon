"""Tests for Tier 2 telemetry samplers — bufferbloat."""

from __future__ import annotations

import json

import pytest

from beacon.telemetry.samplers.bufferbloat import BufferbloatSampler


class TestBufferbloatSampler:
    def test_parse_network_quality_json(self):
        data = {
            "dl_throughput": 150_000_000,
            "ul_throughput": 20_000_000,
            "dl_responsiveness": 1200,
            "interface_name": "en0",
        }
        fields = BufferbloatSampler._parse_network_quality(json.dumps(data))
        assert fields["dl_throughput_mbps"] == 150.0
        assert fields["ul_throughput_mbps"] == 20.0
        assert fields["responsiveness_rpm"] == 1200
        assert fields["interface"] == "en0"

    def test_parse_network_quality_empty(self):
        fields = BufferbloatSampler._parse_network_quality("{}")
        assert fields == {}

    def test_parse_network_quality_invalid_json(self):
        fields = BufferbloatSampler._parse_network_quality("not json")
        assert fields == {}

    def test_parse_iperf3_json(self):
        data = {
            "end": {
                "sum_sent": {
                    "bits_per_second": 100_000_000,
                    "jitter_ms": 0.5,
                },
                "sum_received": {
                    "bits_per_second": 95_000_000,
                },
            }
        }
        fields = BufferbloatSampler._parse_iperf3(json.dumps(data))
        assert fields["ul_throughput_mbps"] == 100.0
        assert fields["dl_throughput_mbps"] == 95.0
        assert fields["jitter_ms"] == 0.5

    def test_parse_iperf3_empty(self):
        fields = BufferbloatSampler._parse_iperf3("{}")
        assert fields == {}

    def test_parse_iperf3_invalid_json(self):
        fields = BufferbloatSampler._parse_iperf3("not json")
        assert fields == {}

    def test_tier(self):
        sampler = BufferbloatSampler()
        assert sampler.tier == 2
        assert sampler.name == "bufferbloat"

    def test_default_interval(self):
        sampler = BufferbloatSampler()
        assert sampler.default_interval == 60
