# GitHub Actions Audit — Beacon

**Date**: 2026-03-08  
**Branch**: `feature/agent-steering-and-skills`

## Executive Summary

Analyzed 5 GitHub Actions workflows. Found **critical version errors** in 3 workflows and identified **7 major automation gaps**.

### Critical Issues

1. **Action version errors**: `lint.yml`, `test.yml`, `release.yml` use non-existent `@v6` versions
2. **No dependency caching**: Slow CI builds, wasted GitHub Actions minutes
3. **No security scanning**: Missing vulnerability detection
4. **Fragile release workflow**: Changelog parsing will break on format changes

### Recommendations Priority

- **P0 (Immediate)**: Fix action version errors
- **P1 (This Sprint)**: Add dependency caching, security scanning
- **P2 (Next Sprint)**: Matrix testing, PyPI publishing, Dependabot

---

## Workflow Analysis

### 1. `docker.yml` — Docker Build and Push

**Status**: ✅ **Excellent**

**What it does**:
- Builds multi-platform Docker images (linux/amd64, linux/arm64)
- Pushes to GitHub Container Registry
- Runs on push to main and PR

**Strengths**:
- Proper Docker Buildx setup
- Multi-platform builds
- Build caching configured
- Correct permissions (`packages: write`)
- Conditional push (only on main)

**Issues**: None

**Recommendation**: No changes needed. This is the gold standard for the other workflows.

---

### 2. `lint.yml` — Code Quality Checks

**Status**: ❌ **Broken**

**What it does**:
- Runs Ruff linting on Python code
- Triggers on push and PR

**Critical Issues**:
```yaml
- uses: actions/checkout@v6  # ❌ v6 doesn't exist, use v4
- uses: actions/setup-python@v6  # ❌ v6 doesn't exist, use v5
```

**Missing**:
- Dependency caching (pip cache)
- MyPy type checking
- Ruff formatting check

**Fixed Version**:

```yaml
name: Lint

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install ruff mypy
          pip install -e ".[dev]"

      - name: Run Ruff linting
        run: ruff check src/ tests/

      - name: Run Ruff formatting check
        run: ruff format --check src/ tests/

      - name: Run MyPy type checking
        run: mypy src/
```

---

### 3. `test.yml` — Unit Tests

**Status**: ❌ **Broken**

**What it does**:
- Runs pytest on Python code
- Generates coverage report
- Triggers on push and PR

**Critical Issues**:
```yaml
- uses: actions/checkout@v6  # ❌ v6 doesn't exist, use v4
- uses: actions/setup-python@v6  # ❌ v6 doesn't exist, use v5
```

**Missing**:
- Dependency caching
- Matrix testing (multiple Python versions)
- Coverage upload to Codecov/Coveralls
- Integration test separation

**Fixed Version**:

```yaml
name: Test

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
        python-version: ['3.11', '3.12']

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install pytest pytest-cov pytest-asyncio
          pip install -e ".[dev]"

      - name: Run unit tests
        run: pytest tests/ --cov=src/beacon --cov-report=xml --cov-report=term -m "not integration"

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
          flags: unittests
          name: ${{ matrix.os }}-${{ matrix.python-version }}
```

---

### 4. `release.yml` — Release Automation

**Status**: ❌ **Broken**

**What it does**:
- Triggers on version tags (`v*`)
- Creates GitHub release
- Extracts changelog from CHANGELOG.md

**Critical Issues**:
```yaml
- uses: actions/checkout@v6  # ❌ v6 doesn't exist, use v4
```

**Major Issues**:
- **Fragile changelog parsing**: Uses `awk` to extract version section, will break on format changes
- **No artifact building**: Doesn't build Python package or binaries
- **No PyPI publishing**: Should publish to PyPI on release
- **No Docker image tagging**: Should tag Docker images with version

**Fixed Version**:

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install build tools
        run: pip install build twine

      - name: Build package
        run: python -m build

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  release:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - name: Download artifacts
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/

      - name: Extract version
        id: version
        run: echo "VERSION=${GITHUB_REF#refs/tags/v}" >> $GITHUB_OUTPUT

      - name: Extract changelog
        id: changelog
        run: |
          VERSION=${{ steps.version.outputs.VERSION }}
          CHANGELOG=$(awk "/## \[${VERSION}\]/,/## \[/" CHANGELOG.md | sed '1d;$d')
          echo "CHANGELOG<<EOF" >> $GITHUB_OUTPUT
          echo "$CHANGELOG" >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v1
        with:
          body: ${{ steps.changelog.outputs.CHANGELOG }}
          files: dist/*
          draft: false
          prerelease: false

  publish-pypi:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      id-token: write  # For trusted publishing
    steps:
      - name: Download artifacts
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1

  tag-docker:
    needs: release
    runs-on: ubuntu-latest
    permissions:
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Extract version
        id: version
        run: echo "VERSION=${GITHUB_REF#refs/tags/v}" >> $GITHUB_OUTPUT

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push versioned image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ghcr.io/${{ github.repository }}:${{ steps.version.outputs.VERSION }}
            ghcr.io/${{ github.repository }}:latest
          platforms: linux/amd64,linux/arm64
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

---

### 5. `stale.yml` — Stale Issue Management

**Status**: ✅ **Adequate**

**What it does**:
- Marks issues/PRs stale after 60 days
- Closes stale items after 7 days
- Runs daily

**Issues**: None critical

**Recommendation**: Consider increasing stale threshold to 90 days given active development.

---

## Missing Workflows

### 1. Security Scanning

**Priority**: P1

**Purpose**: Detect vulnerabilities in dependencies and code

```yaml
name: Security

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: '0 0 * * 0'  # Weekly

jobs:
  dependency-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'fs'
          scan-ref: '.'
          format: 'sarif'
          output: 'trivy-results.sarif'

      - name: Upload Trivy results to GitHub Security
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: 'trivy-results.sarif'

  secret-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run Gitleaks
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  code-scan:
    runs-on: ubuntu-latest
    permissions:
      security-events: write
    steps:
      - uses: actions/checkout@v4

      - name: Initialize CodeQL
        uses: github/codeql-action/init@v3
        with:
          languages: python

      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v3
```

---

### 2. Dependabot Configuration

**Priority**: P1

**Purpose**: Automated dependency updates

Create `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    labels:
      - "dependencies"
      - "python"

  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
    labels:
      - "dependencies"
      - "docker"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    labels:
      - "dependencies"
      - "ci"
```

---

### 3. Integration Tests

**Priority**: P2

**Purpose**: Test cross-component workflows

```yaml
name: Integration Tests

on:
  push:
    branches: [main]
  pull_request:

jobs:
  integration:
    runs-on: ubuntu-latest
    services:
      influxdb:
        image: influxdb:2.7
        ports:
          - 8086:8086
        env:
          DOCKER_INFLUXDB_INIT_MODE: setup
          DOCKER_INFLUXDB_INIT_USERNAME: admin
          DOCKER_INFLUXDB_INIT_PASSWORD: password
          DOCKER_INFLUXDB_INIT_ORG: beacon
          DOCKER_INFLUXDB_INIT_BUCKET: telemetry

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install pytest pytest-asyncio
          pip install -e ".[dev]"

      - name: Run integration tests
        run: pytest tests/integration/ -v -m integration
        env:
          INFLUXDB_URL: http://localhost:8086
          INFLUXDB_TOKEN: test-token
```

---

### 4. Performance Benchmarks

**Priority**: P2

**Purpose**: Track performance regressions

```yaml
name: Benchmarks

on:
  push:
    branches: [main]
  pull_request:

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install pytest pytest-benchmark
          pip install -e ".[dev]"

      - name: Run benchmarks
        run: pytest tests/ -m benchmark --benchmark-only --benchmark-json=output.json

      - name: Store benchmark result
        uses: benchmark-action/github-action-benchmark@v1
        with:
          tool: 'pytest'
          output-file-path: output.json
          github-token: ${{ secrets.GITHUB_TOKEN }}
          auto-push: true
```

---

## Implementation Plan

### Phase 1: Critical Fixes (Immediate)

1. Fix action versions in `lint.yml`, `test.yml`, `release.yml`
2. Add dependency caching to all workflows
3. Test all workflows pass

**Estimated Time**: 1 hour

### Phase 2: Security & Quality (This Sprint)

1. Add security scanning workflow
2. Set up Dependabot
3. Add MyPy to lint workflow
4. Improve test workflow with matrix testing

**Estimated Time**: 3 hours

### Phase 3: Advanced Automation (Next Sprint)

1. Enhance release workflow with PyPI publishing
2. Add integration test workflow
3. Add performance benchmark workflow
4. Set up coverage tracking

**Estimated Time**: 5 hours

---

## Testing Checklist

Before merging workflow changes:

- [ ] All workflows have correct action versions (@v4/@v5, not @v6)
- [ ] Dependency caching configured for Python workflows
- [ ] Workflows tested on feature branch
- [ ] All status checks pass
- [ ] No secrets exposed in logs
- [ ] Permissions follow least-privilege principle
- [ ] Workflow names and job names are descriptive
- [ ] Error handling for external dependencies

---

## Monitoring

After deployment, monitor:

- **Workflow run times**: Should decrease with caching
- **Failure rates**: Should remain low (<5%)
- **Security alerts**: Review weekly
- **Dependabot PRs**: Review and merge weekly
- **Coverage trends**: Should maintain >80%

---

## References

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [actions/checkout@v4](https://github.com/actions/checkout)
- [actions/setup-python@v5](https://github.com/actions/setup-python)
- [Docker Buildx Action](https://github.com/docker/build-push-action)
- [CodeQL Action](https://github.com/github/codeql-action)
