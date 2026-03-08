# Development Workflow — Beacon

## Setup

### Python Environment

Beacon uses Homebrew-managed Python with venv:

```bash
# Create venv
python3 -m venv venv

# Activate
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

### Kiro Agent

The `beacon-dev` agent includes automated hooks for code quality:

```bash
# Use the development agent
kiro-cli chat --agent beacon-dev
```

## Automated Checks (Kiro Hooks)

The `beacon-dev` agent automatically runs:

### After Writing Python Files
- **Ruff formatting**: Auto-formats code
- **Ruff linting**: Auto-fixes issues
- **MyPy type checking**: Validates types (src/ only)

### After Each Agent Turn
- **Pytest**: Runs unit tests (skips integration tests)

### After Writing YAML Files
- **YAML validation**: Checks syntax

**No manual intervention needed** - hooks run automatically when the agent modifies code.

## Manual Commands

### Testing

```bash
# All unit tests
pytest tests/ -m "not integration"

# Specific test file
pytest tests/collectors/test_wifi.py

# With coverage
pytest tests/ --cov=src/beacon --cov-report=html

# Integration tests (requires InfluxDB)
pytest tests/integration/ -m integration
```

### Linting

```bash
# Check and auto-fix
ruff check --fix src/ tests/

# Format
ruff format src/ tests/

# Check only (no changes)
ruff check src/ tests/
```

### Type Checking

```bash
# Check all source
mypy src/

# Specific file
mypy src/beacon/collectors/wifi.py
```

## CI/CD

GitHub Actions runs on every push:
- Linting (ruff)
- Type checking (mypy)
- Unit tests (pytest)
- Docker build

See `docs/github-actions-audit.md` for workflow details.

## Development Cycle

1. **Make changes** (agent or manual)
2. **Hooks auto-run** (formatting, linting, type checking)
3. **Review output** (warnings shown in chat)
4. **Commit when ready** (batch multiple changes)
5. **Push** (CI validates everything)

## Troubleshooting

### Hooks not running

Check agent is active:
```bash
kiro-cli chat --agent beacon-dev
```

### Tests failing

Run manually to see full output:
```bash
pytest tests/ -v
```

### Type errors

MyPy is strict - add type hints or use `# type: ignore` with justification.

### Venv not activated

Hooks auto-activate venv if `venv/bin/activate` exists.
