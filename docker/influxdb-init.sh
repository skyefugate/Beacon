#!/bin/bash
# Create the beacon_telemetry bucket if it doesn't exist.
# InfluxDB auto-creates the primary bucket (beacon) via env vars,
# but the telemetry subsystem uses a separate bucket.

set -e

# Wait for InfluxDB to be ready
until influx ping > /dev/null 2>&1; do
    echo "Waiting for InfluxDB..."
    sleep 2
done

# Create telemetry bucket (ignore error if it already exists)
influx bucket create \
    --name beacon_telemetry \
    --org beacon \
    --retention 30d \
    --token beacon-dev-token \
    2>/dev/null || true

echo "InfluxDB init complete — beacon_telemetry bucket ready"
