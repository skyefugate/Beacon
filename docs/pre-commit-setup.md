# Pre-commit Setup

Beacon uses [pre-commit](https://pre-commit.com/) to enforce code quality standards before commits.

## Installation

```bash
# Install pre-commit
pip install pre-commit

# Install the git hooks
pre-commit install
```

## What Gets Checked

Every commit automatically runs:

1. **Ruff** - Linting and formatting (auto-fixes issues)
2. **MyPy** - Type checking (strict mode on `src/`)
3. **Pytest** - Unit tests (fails fast on first error)
4. **Standard checks** - Trailing whitespace, YAML syntax, merge conflicts

## Manual Run

Test hooks without committing:

```bash
# Run on all files
pre-commit run --all-files

# Run on staged files only
pre-commit run
```

## Skipping Hooks (Emergency Only)

```bash
# Skip all hooks (not recommended)
git commit --no-verify

# Skip specific hook
SKIP=pytest git commit
```

## Updating Hooks

```bash
pre-commit autoupdate
```

## Troubleshooting

**Hook fails on import errors:**
- Ensure dependencies installed: `pip install -e ".[dev]"`

**MyPy complains about missing types:**
- Add `# type: ignore` comment with justification
- Or install type stubs: `pip install types-<package>`

**Tests fail:**
- Fix tests before committing
- Or use `SKIP=pytest` if tests are unrelated to your changes (discouraged)
