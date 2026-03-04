"""Telemetry API routes — structured endpoints for the agent dashboard.

Provides three endpoints that transform raw InfluxDB Flux results into
frontend-friendly JSON. All Flux queries are constructed server-side with
allowlisted parameters to prevent injection.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from beacon import __version__
from beacon.api.bxi import compute_bxi
from beacon.api.deps import get_beacon_settings, get_influx_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

# --- Allowlists (prevent Flux injection) ---

ALLOWED_MEASUREMENTS = {
    "t_internet_rtt_agg",
    "t_dns_latency_agg",
    "t_http_timing_agg",
    "t_device_health_agg",
}

ALLOWED_FIELDS: dict[str, set[str]] = {
    "t_internet_rtt_agg": {
        "rtt_avg_ms_mean",
        "rtt_avg_ms_p50",
        "rtt_avg_ms_p95",
        "rtt_avg_ms_p99",
        "rtt_avg_ms_min",
        "rtt_avg_ms_max",
        "rtt_avg_ms_stddev",
        "loss_pct_mean",
        "loss_pct_max",
    },
    "t_dns_latency_agg": {
        "latency_ms_mean",
        "latency_ms_p50",
        "latency_ms_p95",
        "latency_ms_p99",
        "latency_ms_min",
        "latency_ms_max",
        "latency_ms_stddev",
    },
    "t_http_timing_agg": {
        "total_ms_mean",
        "total_ms_p50",
        "total_ms_p95",
        "total_ms_p99",
        "total_ms_min",
        "total_ms_max",
        "total_ms_stddev",
        "ttfb_ms_mean",
        "ttfb_ms_p50",
        "ttfb_ms_p95",
        "status_code_mode",
    },
    "t_device_health_agg": {
        "cpu_percent_mean",
        "cpu_percent_max",
        "memory_percent_mean",
        "memory_percent_max",
        "disk_percent_mean",
    },
}

ALLOWED_RANGES = {"5m", "15m", "1h", "6h", "24h", "7d"}

# Short names for the frontend → full measurement names
MEASUREMENT_ALIASES = {
    "internet_rtt": "t_internet_rtt_agg",
    "dns_latency": "t_dns_latency_agg",
    "http_timing": "t_http_timing_agg",
    "device_health": "t_device_health_agg",
}

# Process start time for uptime calculation
_start_time = time.monotonic()


def _get_bucket() -> str:
    """Read telemetry bucket name from settings."""
    settings = get_beacon_settings()
    return settings.telemetry.export_influx_bucket


def _resolve_measurement(measurement: str) -> str:
    """Resolve a short alias or full measurement name."""
    if measurement in MEASUREMENT_ALIASES:
        return MEASUREMENT_ALIASES[measurement]
    if measurement in ALLOWED_MEASUREMENTS:
        return measurement
    raise ValueError(f"Unknown measurement: {measurement}")


def _validate_field(measurement: str, field: str) -> None:
    """Validate a field name against the allowlist for a measurement."""
    allowed = ALLOWED_FIELDS.get(measurement, set())
    if field not in allowed:
        raise ValueError(f"Field '{field}' not allowed for {measurement}")


def _group_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Group flat InfluxDB records into {measurement: {field: value}} structure."""
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        meas = record.get("_measurement", "unknown")
        field = record.get("_field", "unknown")
        value = record.get("_value")
        if meas not in grouped:
            grouped[meas] = {}
        grouped[meas][field] = value
    return grouped


@router.get("/overview")
async def telemetry_overview() -> dict[str, Any]:
    """BXI score + latest values for all measurements + agent info.

    Queries the last() value from each _agg measurement in the past 5 minutes.
    """
    influx = get_influx_storage()
    if not influx:
        raise HTTPException(status_code=503, detail="InfluxDB is not available")

    bucket = _get_bucket()
    settings = get_beacon_settings()

    try:
        flux = f"""
from(bucket: "{bucket}")
  |> range(start: -5m)
  |> filter(fn: (r) => r["_measurement"] =~ /^t_.*_agg$/)
  |> last()
"""
        records = influx.query(flux)

        # Context data: raw string fields (not aggregated)
        context_flux = f"""
from(bucket: "{bucket}")
  |> range(start: -5m)
  |> filter(fn: (r) => r["_measurement"] == "t_agent_context" or r["_measurement"] == "t_network_geo")
  |> last()
"""
        context_records = influx.query(context_flux)
    except Exception as e:
        logger.error("InfluxDB overview query failed: %s", e)
        raise HTTPException(status_code=503, detail="InfluxDB query failed")
    finally:
        influx.close()

    grouped = _group_records(records)

    # Extract BXI input metrics from grouped data
    rtt_data = grouped.get("t_internet_rtt_agg", {})
    dns_data = grouped.get("t_dns_latency_agg", {})
    http_data = grouped.get("t_http_timing_agg", {})

    bxi_input = {
        "rtt_p95_ms": rtt_data.get("rtt_avg_ms_p95"),
        "loss_pct": rtt_data.get("loss_pct_mean"),
        "dns_p95_ms": dns_data.get("latency_ms_p95"),
        "http_p95_ms": http_data.get("total_ms_p95"),
        "jitter_ms": rtt_data.get("rtt_avg_ms_stddev"),
    }

    bxi = compute_bxi(bxi_input)

    # Build friendly metric names (strip t_ prefix and _agg suffix)
    metrics: dict[str, Any] = {}
    for full_name, fields in grouped.items():
        short = full_name.removeprefix("t_").removesuffix("_agg")
        metrics[short] = fields

    # Build context data from raw measurements
    context_grouped = _group_records(context_records)
    context: dict[str, Any] = {}
    context.update(context_grouped.get("t_agent_context", {}))
    context.update(context_grouped.get("t_network_geo", {}))

    return {
        "bxi": {
            "score": bxi.score,
            "label": bxi.label,
            "color": bxi.color,
            "components": bxi.components,
        },
        "metrics": metrics,
        "context": context,
        "escalation": {"state": "BASELINE", "since": None},
        "agent": {
            "probe_id": settings.probe_id,
            "version": __version__,
            "uptime_seconds": int(time.monotonic() - _start_time),
        },
    }


@router.get("/series")
async def telemetry_series(
    measurement: str = Query(..., description="Measurement name or alias"),
    field: str = Query(..., description="Field name to query"),
    range: str = Query("1h", description="Time range"),
) -> dict[str, Any]:
    """Time series data for a single measurement/field combination."""
    if range not in ALLOWED_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid range '{range}'. Allowed: {sorted(ALLOWED_RANGES)}",
        )

    try:
        full_measurement = _resolve_measurement(measurement)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        _validate_field(full_measurement, field)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    influx = get_influx_storage()
    if not influx:
        raise HTTPException(status_code=503, detail="InfluxDB is not available")

    bucket = _get_bucket()

    try:
        flux = f"""
from(bucket: "{bucket}")
  |> range(start: -{range})
  |> filter(fn: (r) => r["_measurement"] == "{full_measurement}")
  |> filter(fn: (r) => r["_field"] == "{field}")
  |> sort(columns: ["_time"])
"""
        records = influx.query(flux)
    except Exception as e:
        logger.error("InfluxDB series query failed: %s", e)
        raise HTTPException(status_code=503, detail="InfluxDB query failed")
    finally:
        influx.close()

    points = []
    for r in records:
        t = r.get("_time")
        points.append(
            {
                "time": t.isoformat() if t and hasattr(t, "isoformat") else str(t),
                "value": r.get("_value"),
            }
        )

    return {
        "measurement": measurement,
        "field": field,
        "range": range,
        "points": points,
    }


@router.get("/sparklines")
async def telemetry_sparklines(
    range: str = Query("1h", description="Time range"),
) -> dict[str, Any]:
    """Batch mini-series for all metric cards, downsampled to ~50 points."""
    if range not in ALLOWED_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid range '{range}'. Allowed: {sorted(ALLOWED_RANGES)}",
        )

    # Compute aggregate window for ~50 points
    range_seconds = {
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "24h": 86400,
        "7d": 604800,
    }
    total = range_seconds[range]
    window_seconds = max(total // 50, 10)

    influx = get_influx_storage()
    if not influx:
        raise HTTPException(status_code=503, detail="InfluxDB is not available")

    bucket = _get_bucket()

    # Key fields for sparklines — one per metric card
    sparkline_fields = {
        "internet_rtt": ("t_internet_rtt_agg", "rtt_avg_ms_mean"),
        "dns_latency": ("t_dns_latency_agg", "latency_ms_mean"),
        "http_timing": ("t_http_timing_agg", "total_ms_mean"),
        "packet_loss": ("t_internet_rtt_agg", "loss_pct_mean"),
        "cpu": ("t_device_health_agg", "cpu_percent_mean"),
        "memory": ("t_device_health_agg", "memory_percent_mean"),
    }

    sparklines: dict[str, list[dict[str, Any]]] = {}

    try:
        for key, (meas, fld) in sparkline_fields.items():
            flux = f"""
from(bucket: "{bucket}")
  |> range(start: -{range})
  |> filter(fn: (r) => r["_measurement"] == "{meas}")
  |> filter(fn: (r) => r["_field"] == "{fld}")
  |> aggregateWindow(every: {window_seconds}s, fn: mean, createEmpty: false)
  |> sort(columns: ["_time"])
"""
            records = influx.query(flux)
            points = []
            for r in records:
                t = r.get("_time")
                points.append(
                    {
                        "time": t.isoformat() if t and hasattr(t, "isoformat") else str(t),
                        "value": r.get("_value"),
                    }
                )
            sparklines[key] = points
    except Exception as e:
        logger.error("InfluxDB sparklines query failed: %s", e)
        raise HTTPException(status_code=503, detail="InfluxDB query failed")
    finally:
        influx.close()

    return {
        "range": range,
        "window_seconds": window_seconds,
        "sparklines": sparklines,
    }
