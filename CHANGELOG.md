# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-02-02

### Added
- **Core Engine**:
  - Real-time order book reconstruction via WebSocket (Binance Futures)
  - Asyncio-based architecture using `uvloop` for high performance
  - O(log n) order book management using `SortedDict`
  - Liquidity crunch detection using Z-score analysis
  - Risk metrics calculation (slippage, depth, imbalance)

- **Infrastructure & Quality**:
  - Complete CI/CD pipeline with GitHub Actions
  - PostgreSQL integration via `asyncpg`
  - Strict type checking (`mypy --strict`)
  - Automated testing suite (Unit, Integration, and Performance benchmarks)
  - Security scanning (`bandit`) and dependency auditing
  - Structured logging with performance tracing

### Technical Details
- Implemented robust race condition handling for WebSocket streams
- Zero-copy optimizations for snapshot processing
- Clean architecture with separation of concerns

---
[0.1.0]: https://github.com/JudyChang-TW/liquidity-crunch-monitor/releases/tag/v0.1.0
