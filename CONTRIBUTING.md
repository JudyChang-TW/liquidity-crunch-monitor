# Contributing to Liquidity-Crunch-Monitor

We enforce strict engineering standards to ensure low latency and high reliability suitable for high-frequency trading contexts.


##  Engineering Standards

- **Type Safety:** 100% type coverage required (`mypy --strict`).
- **Performance:** No blocking I/O allowed in critical paths. Use `uvloop` compatible patterns.
- **Documentation:** Google-style docstrings required for all public interfaces.
- **Testing:**
    - Unit tests: Logic validation.
    - Integration tests: WebSocket/DB interactions.
    - **Benchmarks:** Critical paths (e.g., OrderBook updates) must verify latency via `pytest-benchmark`.


## Quick Start

```bash
# 1. Setup Environment
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# 2. Install Git Hooks (MANDATORY)
pre-commit install
```


## Testing & Quality Gate

Before submitting a PR, ensure all checks pass:

### Level 1: Local Quick Checks
```bash
# Format and lint
pre-commit run --all-files

# Run tests
pytest tests/ -v

# Or use Makefile
make check  # Runs format + lint + test
```

### Level 2: CI Validation (Recommended)
Use **act** to run GitHub Actions locally and catch CI failures before pushing:

```bash
# One-time setup
make act-setup

# Before pushing - verify CI will pass
make quick-check      # pre-commit + tests + act CI

# Or run specific CI jobs
make act-test         # Run CI test suite
make act-lint         # Run CI linting
make act-all          # Run full CI pipeline
```

**Why use act?**
- ✅ Catches environment-specific failures
- ✅ Tests Python 3.10/3.11/3.12 matrix locally
- ✅ Validates in identical Ubuntu CI environment
- ✅ 45s feedback vs 2-4min on GitHub

See [QUICK_START_ACT.md](QUICK_START_ACT.md) for details.

### Level 3: Benchmarks
```bash
# Verify no performance regression
pytest tests/performance/ --benchmark-only
```


## Pull Request Checklist

- [ ] Code formatted with `black` and `isort`
- [ ] `pre-commit run --all-files` passes
- [ ] `mypy` passes in strict mode
- [ ] Test coverage remains > 70% (core: > 85%)
- [ ] **`make act-all` passes (CI validation)**
- [ ] No regression in order book processing latency
- [ ] Database migrations included (if schema changed)
- [ ] Documentation updated (if needed)


## Security

Never commit API keys, secrets, or production .env files.
Use bandit to scan for common security issues before pushing.
