#!/usr/bin/env bash
# Beacon development environment setup script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "==> Setting up Beacon development environment"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "==> Creating virtual environment"
    python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Install in development mode
echo "==> Installing beacon with dev dependencies"
pip install -e ".[dev]"

# Create local data directories
echo "==> Creating local data directories"
mkdir -p data/artifacts data/evidence

# Copy .env.example if .env doesn't exist
if [ ! -f ".env" ]; then
    echo "==> Creating .env from .env.example"
    cp .env.example .env
    # Override for local development
    cat >> .env <<EOF

# Local development overrides
INFLUXDB_URL=http://localhost:8086
COLLECTOR_URL=http://localhost:9100
BEACON_DATA_DIR=./data
BEACON_ARTIFACT_DIR=./data/artifacts
BEACON_EVIDENCE_DIR=./data/evidence
EOF
fi

# Run tests
echo "==> Running tests"
python -m pytest tests/unit/ -v

echo ""
echo "==> Setup complete!"
echo ""
echo "Activate the venv:  source .venv/bin/activate"
echo "Run tests:          pytest tests/"
echo "Start server:       beacon server start"
echo "List packs:         beacon packs list"
echo "Run a diagnostic:   beacon run quick_health"
echo "Docker:             docker compose up"
