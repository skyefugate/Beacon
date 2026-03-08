"""Signal sets and heuristic rule sets for fault domain classification.

Each fault domain has a set of signals (metric patterns) that indicate
a problem in that domain. The HeuristicRuleSet evaluates all signals
against collected data to produce per-domain scores.
"""

from __future__ import annotations

from dataclasses import dataclass

from beacon.models.envelope import Event, Metric, PluginEnvelope
from beacon.models.fault import FaultDomain


@dataclass
class Signal:
    """A single signal that contributes to a fault domain's score."""

    domain: FaultDomain
    name: str
    weight: float = 1.0
    description: str = ""


@dataclass
class SignalMatch:
    """A signal that matched against collected data."""

    signal: Signal
    evidence_ref: str
    value: float | str | None = None


# Built-in signal definitions
SIGNALS: list[Signal] = [
    # Device domain
    Signal(FaultDomain.DEVICE, "high_cpu", 0.8, "CPU usage >90%"),
    Signal(FaultDomain.DEVICE, "high_memory", 0.8, "Memory usage >90%"),
    Signal(FaultDomain.DEVICE, "high_temperature", 0.6, "CPU temperature critical"),
    Signal(FaultDomain.DEVICE, "disk_io_slow", 0.7, "Disk I/O latency >50ms"),
    Signal(FaultDomain.DEVICE, "disk_near_full", 0.8, "Disk usage >85%"),
    Signal(FaultDomain.DEVICE, "disk_io_critical", 0.9, "Disk I/O latency >200ms"),
    # Wi-Fi domain
    Signal(FaultDomain.WIFI, "weak_signal", 0.9, "Wi-Fi RSSI below -75 dBm"),
    Signal(FaultDomain.WIFI, "low_snr", 0.7, "Signal-to-noise ratio below 15 dB"),
    Signal(FaultDomain.WIFI, "wifi_assoc_failure", 1.0, "Wi-Fi association failure"),
    Signal(FaultDomain.WIFI, "wifi_roam", 0.4, "SSID or AP change detected"),
    # LAN domain
    Signal(FaultDomain.LAN, "link_down", 1.0, "Network interface is down"),
    Signal(FaultDomain.LAN, "link_flap", 0.9, "Interface is flapping"),
    Signal(FaultDomain.LAN, "interface_errors", 0.6, "Interface errors detected"),
    Signal(FaultDomain.LAN, "gateway_unreachable", 0.9, "Default gateway unreachable"),
    # ISP domain
    Signal(FaultDomain.ISP, "high_latency_external", 0.7, "High latency to external targets"),
    Signal(FaultDomain.ISP, "packet_loss_external", 0.8, "Packet loss to external targets"),
    Signal(FaultDomain.ISP, "traceroute_blackhole", 0.7, "Traceroute blackhole detected"),
    # DNS domain
    Signal(FaultDomain.DNS, "dns_failure", 1.0, "DNS resolution failure"),
    Signal(FaultDomain.DNS, "dns_timeout", 0.9, "DNS resolution timeout"),
    Signal(FaultDomain.DNS, "slow_dns", 0.6, "DNS resolution slow (>500ms)"),
    # App/SaaS domain
    Signal(FaultDomain.APP_SAAS, "http_error", 0.8, "HTTP 4xx/5xx response"),
    Signal(FaultDomain.APP_SAAS, "http_timeout", 0.7, "HTTP connection or read timeout"),
    Signal(FaultDomain.APP_SAAS, "slow_http", 0.5, "Slow HTTP response (>2s)"),
]


class HeuristicRuleSet:
    """Evaluates plugin envelopes against signal definitions to find matches."""

    def __init__(self, signals: list[Signal] | None = None) -> None:
        self._signals = signals or SIGNALS
        self._signal_map: dict[str, Signal] = {s.name: s for s in self._signals}

    def evaluate(self, envelopes: list[PluginEnvelope]) -> list[SignalMatch]:
        """Scan all envelopes for signal matches."""
        matches: list[SignalMatch] = []

        all_metrics: list[Metric] = []
        all_events: list[Event] = []
        for env in envelopes:
            all_metrics.extend(env.metrics)
            all_events.extend(env.events)

        # Match events to signals by event_type
        for event in all_events:
            signal = self._signal_map.get(event.event_type)
            if signal:
                ref = f"event:{event.event_type}:{','.join(f'{k}={v}' for k, v in event.tags.items())}"
                matches.append(SignalMatch(signal=signal, evidence_ref=ref))

        # Match metrics to domain signals
        for metric in all_metrics:
            matches.extend(self._check_metric_signals(metric))

        return matches

    def _check_metric_signals(self, metric: Metric) -> list[SignalMatch]:
        """Check a metric for known signal patterns."""
        matches: list[SignalMatch] = []
        m = metric.measurement
        f = metric.fields
        tags = metric.tags

        # Device signals
        percent = f.get("percent")
        if m == "device_cpu" and isinstance(percent, (int, float)) and percent > 90:
            matches.append(
                SignalMatch(
                    signal=self._signal_map["high_cpu"],
                    evidence_ref=f"metric:device_cpu:percent={percent}",
                    value=percent,
                )
            )

        percent_used = f.get("percent_used")
        if m == "device_memory" and isinstance(percent_used, (int, float)) and percent_used > 90:
            matches.append(
                SignalMatch(
                    signal=self._signal_map["high_memory"],
                    evidence_ref=f"metric:device_memory:percent_used={percent_used}",
                    value=percent_used,
                )
            )

        # Disk signals
        if m == "t_disk_usage":
            used_percent = f.get("used_percent")
            if isinstance(used_percent, (int, float)) and used_percent > 85:
                matches.append(
                    SignalMatch(
                        signal=self._signal_map["disk_near_full"],
                        evidence_ref=f"metric:t_disk_usage:used_percent={used_percent}",
                        value=used_percent,
                    )
                )

        if m == "t_disk_io":
            avg_latency_ms = f.get("avg_latency_ms")
            if isinstance(avg_latency_ms, (int, float)):
                if avg_latency_ms > 200:
                    matches.append(
                        SignalMatch(
                            signal=self._signal_map["disk_io_critical"],
                            evidence_ref=f"metric:t_disk_io:avg_latency_ms={avg_latency_ms}",
                            value=avg_latency_ms,
                        )
                    )
                elif avg_latency_ms > 50:
                    matches.append(
                        SignalMatch(
                            signal=self._signal_map["disk_io_slow"],
                            evidence_ref=f"metric:t_disk_io:avg_latency_ms={avg_latency_ms}",
                            value=avg_latency_ms,
                        )
                    )

        # Wi-Fi signals
        if m == "wifi_link":
            rssi = f.get("rssi_dbm")
            if isinstance(rssi, (int, float)) and rssi < -75:
                matches.append(
                    SignalMatch(
                        signal=self._signal_map["weak_signal"],
                        evidence_ref=f"metric:wifi_link:rssi_dbm={rssi}",
                        value=rssi,
                    )
                )

        # Ping signals (external targets → ISP domain)
        if m == "ping":
            loss = f.get("loss_pct")
            if isinstance(loss, (int, float)) and loss > 5:
                matches.append(
                    SignalMatch(
                        signal=self._signal_map["packet_loss_external"],
                        evidence_ref=f"metric:ping:{tags.get('target', '')}:loss_pct={loss}",
                        value=loss,
                    )
                )
            rtt = f.get("rtt_avg_ms")
            if isinstance(rtt, (int, float)) and rtt > 100:
                matches.append(
                    SignalMatch(
                        signal=self._signal_map["high_latency_external"],
                        evidence_ref=f"metric:ping:{tags.get('target', '')}:rtt_avg_ms={rtt}",
                        value=rtt,
                    )
                )

        # Gateway signals
        if m == "path_gateway":
            if f.get("reachable") is False:
                matches.append(
                    SignalMatch(
                        signal=self._signal_map["gateway_unreachable"],
                        evidence_ref=f"metric:path_gateway:{tags.get('gateway', '')}:unreachable",
                    )
                )

        # DNS signals
        if m == "dns_resolve":
            if f.get("success") is False:
                matches.append(
                    SignalMatch(
                        signal=self._signal_map["dns_failure"],
                        evidence_ref=f"metric:dns_resolve:{tags.get('resolver', '')}:{tags.get('domain', '')}:failure",
                    )
                )
            latency = f.get("latency_ms")
            if isinstance(latency, (int, float)) and latency > 500:
                matches.append(
                    SignalMatch(
                        signal=self._signal_map["slow_dns"],
                        evidence_ref=f"metric:dns_resolve:{tags.get('resolver', '')}:{tags.get('domain', '')}:latency={latency}",
                        value=latency,
                    )
                )

        # HTTP signals
        if m == "http_timing":
            status = f.get("status_code")
            if isinstance(status, (int, float)) and status >= 400:
                matches.append(
                    SignalMatch(
                        signal=self._signal_map["http_error"],
                        evidence_ref=f"metric:http_timing:{tags.get('url', '')}:status={status}",
                        value=status,
                    )
                )
            if f.get("success") is False and (not isinstance(status, (int, float)) or status == 0):
                matches.append(
                    SignalMatch(
                        signal=self._signal_map["http_timeout"],
                        evidence_ref=f"metric:http_timing:{tags.get('url', '')}:timeout",
                    )
                )
            total = f.get("total_ms")
            if isinstance(total, (int, float)) and total > 2000:
                matches.append(
                    SignalMatch(
                        signal=self._signal_map["slow_http"],
                        evidence_ref=f"metric:http_timing:{tags.get('url', '')}:total_ms={total}",
                        value=total,
                    )
                )

        # LAN interface signals
        if m == "lan_interface":
            errin = f.get("errin", 0)
            errout = f.get("errout", 0)
            if isinstance(errin, (int, float)) and isinstance(errout, (int, float)):
                if errin > 0 or errout > 0:
                    matches.append(
                        SignalMatch(
                            signal=self._signal_map["interface_errors"],
                            evidence_ref=f"metric:lan_interface:{tags.get('interface', '')}:errin={errin},errout={errout}",
                            value=errin + errout,
                        )
                    )

        # LAN link status signals — only flag physical/active interfaces
        # Virtual tunnel stubs (gif*, stf*, utun*, etc.) are normally down
        if m == "lan_status":
            iface = tags.get("interface", "")
            _VIRTUAL_PREFIXES = ("gif", "stf", "utun", "awdl", "llw", "ap", "bridge", "anpi")
            is_virtual = any(iface.startswith(p) for p in _VIRTUAL_PREFIXES)
            if f.get("is_up") is False and not is_virtual:
                matches.append(
                    SignalMatch(
                        signal=self._signal_map["link_down"],
                        evidence_ref=f"metric:lan_status:{iface}:down",
                    )
                )

        # Traceroute signals — use summary metric, not individual hops.
        # Individual timeout hops are normal (ICMP rate limiting by routers).
        # The runner already emits a traceroute_blackhole event for 3+ consecutive
        # timeouts; we only flag here if majority of hops timed out.
        if m == "traceroute_summary":
            total = f.get("total_hops", 0)
            timeouts = f.get("timeout_hops", 0)
            if isinstance(total, (int, float)) and isinstance(timeouts, (int, float)):
                if total > 0 and timeouts / total > 0.5:
                    matches.append(
                        SignalMatch(
                            signal=self._signal_map["traceroute_blackhole"],
                            evidence_ref=f"metric:traceroute_summary:{tags.get('target', '')}:timeouts={timeouts}/{total}",
                            value=timeouts,
                        )
                    )

        return matches
