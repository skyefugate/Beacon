"""Tests for DNS runner - focusing on error paths and edge cases."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import dns.exception
import dns.resolver
import pytest

from beacon.runners.base import RunnerConfig
from beacon.runners.dns import DNSRunner


class TestDNSRunner:
    def test_successful_resolution(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            
            mock_answer = MagicMock()
            mock_answer.address = "142.250.80.46"
            mock_res.resolve.return_value = [mock_answer]

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["google.com"],
                extra={"resolvers": ["8.8.8.8"]},
            )
            envelope = runner.run(uuid4(), config)

            assert envelope.plugin_name == "dns"
            assert len(envelope.metrics) == 1
            assert envelope.metrics[0].fields["success"] is True
            assert envelope.metrics[0].fields["answer_count"] == 1
            assert envelope.metrics[0].fields["first_answer"] == "142.250.80.46"

    def test_default_resolvers_and_domains(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            
            mock_answer = MagicMock()
            mock_answer.address = "1.2.3.4"
            mock_res.resolve.return_value = [mock_answer]

            runner = DNSRunner()
            config = RunnerConfig()  # No targets or resolvers specified
            envelope = runner.run(uuid4(), config)

            # Should use defaults: 3 resolvers × 2 domains = 6 metrics
            assert len(envelope.metrics) == 6

    def test_multiple_answers(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            
            mock_answers = [MagicMock(), MagicMock(), MagicMock()]
            mock_answers[0].address = "1.2.3.4"
            mock_answers[1].address = "5.6.7.8"
            mock_answers[2].address = "9.10.11.12"
            mock_res.resolve.return_value = mock_answers

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["example.com"],
                extra={"resolvers": ["8.8.8.8"]},
            )
            envelope = runner.run(uuid4(), config)

            assert envelope.metrics[0].fields["answer_count"] == 3
            assert envelope.metrics[0].fields["first_answer"] == "1.2.3.4"

    def test_slow_dns_event(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver, \
             patch("beacon.runners.dns.time.monotonic") as mock_time:
            
            # Mock slow resolution (600ms)
            mock_time.side_effect = [0, 0.6]
            
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            
            mock_answer = MagicMock()
            mock_answer.address = "1.2.3.4"
            mock_res.resolve.return_value = [mock_answer]

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["slow.example.com"],
                extra={"resolvers": ["8.8.8.8"]},
            )
            envelope = runner.run(uuid4(), config)

            slow_events = [e for e in envelope.events if e.event_type == "slow_dns"]
            assert len(slow_events) == 1
            assert "600ms" in slow_events[0].message

    def test_nxdomain_error(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            mock_res.resolve.side_effect = dns.resolver.NXDOMAIN()

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["nonexistent.invalid"],
                extra={"resolvers": ["8.8.8.8"]},
            )
            envelope = runner.run(uuid4(), config)

            assert envelope.metrics[0].fields["success"] is False
            assert envelope.metrics[0].fields["error"] == "NXDOMAIN"
            
            dns_events = [e for e in envelope.events if e.event_type == "dns_failure"]
            assert len(dns_events) == 1
            assert "NXDOMAIN" in dns_events[0].message

    def test_no_nameservers_error(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            mock_res.resolve.side_effect = dns.resolver.NoNameservers()

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["example.com"],
                extra={"resolvers": ["192.0.2.1"]},  # Non-responsive resolver
            )
            envelope = runner.run(uuid4(), config)

            assert envelope.metrics[0].fields["success"] is False
            assert envelope.metrics[0].fields["error"] == "no_nameservers"
            
            dns_events = [e for e in envelope.events if e.event_type == "dns_failure"]
            assert len(dns_events) == 1
            assert "No nameservers" in dns_events[0].message

    def test_timeout_error(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            mock_res.resolve.side_effect = dns.exception.Timeout()

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["example.com"],
                extra={"resolvers": ["10.0.0.1"]},  # Timeout resolver
            )
            envelope = runner.run(uuid4(), config)

            assert envelope.metrics[0].fields["success"] is False
            assert envelope.metrics[0].fields["error"] == "timeout"
            
            timeout_events = [e for e in envelope.events if e.event_type == "dns_timeout"]
            assert len(timeout_events) == 1

    def test_generic_exception(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            mock_res.resolve.side_effect = Exception("Unexpected DNS error")

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["example.com"],
                extra={"resolvers": ["8.8.8.8"]},
            )
            envelope = runner.run(uuid4(), config)

            assert any("failed" in note for note in envelope.notes)

    def test_resolver_configuration(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            
            mock_answer = MagicMock()
            mock_answer.address = "1.2.3.4"
            mock_res.resolve.return_value = [mock_answer]

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["example.com"],
                extra={"resolvers": ["1.1.1.1"]},
                timeout_seconds=5
            )
            envelope = runner.run(uuid4(), config)

            # Verify resolver was configured correctly
            assert mock_res.nameservers == ["1.1.1.1"]
            assert mock_res.lifetime == 5

    def test_empty_answer_list(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            mock_res.resolve.return_value = []  # Empty answer list

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["example.com"],
                extra={"resolvers": ["8.8.8.8"]},
            )
            envelope = runner.run(uuid4(), config)

            assert envelope.metrics[0].fields["success"] is True
            assert envelope.metrics[0].fields["answer_count"] == 0
            assert envelope.metrics[0].fields["first_answer"] == ""

    def test_multiple_resolvers_and_domains(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            
            mock_answer = MagicMock()
            mock_answer.address = "1.2.3.4"
            mock_res.resolve.return_value = [mock_answer]

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["example.com", "test.com"],
                extra={"resolvers": ["8.8.8.8", "1.1.1.1"]},
            )
            envelope = runner.run(uuid4(), config)

            # 2 resolvers × 2 domains = 4 metrics
            assert len(envelope.metrics) == 4
            
            # Verify all combinations are tested
            resolver_domain_pairs = {
                (m.tags["resolver"], m.tags["domain"]) 
                for m in envelope.metrics
            }
            expected_pairs = {
                ("8.8.8.8", "example.com"),
                ("8.8.8.8", "test.com"),
                ("1.1.1.1", "example.com"),
                ("1.1.1.1", "test.com"),
            }
            assert resolver_domain_pairs == expected_pairs

    def test_timing_measurement(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver, \
             patch("beacon.runners.dns.time.monotonic") as mock_time:
            
            # Mock 50ms resolution time
            mock_time.side_effect = [0, 0.05]
            
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            
            mock_answer = MagicMock()
            mock_answer.address = "1.2.3.4"
            mock_res.resolve.return_value = [mock_answer]

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["example.com"],
                extra={"resolvers": ["8.8.8.8"]},
            )
            envelope = runner.run(uuid4(), config)

            assert envelope.metrics[0].fields["latency_ms"] == 50.0