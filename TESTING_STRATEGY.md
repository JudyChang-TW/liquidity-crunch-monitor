# Testing Strategy

## Philosophy

This project follows a **pragmatic, layered testing approach** that prioritizes core business logic over infrastructure code. This strategy is common in production HFT/fintech systems where external dependencies (exchanges, databases) are tested through integration tests rather than unit tests.

## Coverage Metrics

### Current Coverage (by Layer)

| Layer | Coverage Target | Rationale |
|-------|----------------|-----------|
| **Core Logic** | 85%+ | OrderBook, RiskEngine, metrics - pure Python, no I/O |
| **Infrastructure** | Integration Tests | Connectors (WebSocket), Database (PostgreSQL) |
| **Overall** | 85%+ (core only) | Meaningful metric for testable logic |

### Why Exclude Infrastructure from Coverage?

```python
# ❌ Hard to unit test (requires real exchanges)
class BinanceOrderBookManager:
    async def connect(self):
        self.websocket = await websockets.connect(...)

# ❌ Hard to unit test (requires PostgreSQL)
class DatabaseWriter:
    async def write_anomaly(self, event):
        await self.pool.execute("INSERT INTO ...")

# ✅ Easy to unit test (pure Python logic)
class OrderBook:
    def update_bid(self, price: Decimal, qty: Decimal):
        if qty == 0:
            self.bids.pop(price, None)
        else:
            self.bids[price] = qty
```

## Test Organization

### Unit Tests (`tests/unit/`)
- **Pure logic, no I/O**
- Fast execution (<1s total)
- No external dependencies
- 85%+ coverage target

**Covered modules:**
- `core/orderbook.py` - Order book data structure
- `analytics/risk_engine.py` - Slippage, depth, anomaly detection
- `utils/` - Helper functions

### Integration Tests (`tests/integration/`)
- **Real WebSocket connections** (with mocking for CI)
- **Database operations**
- Slower execution (requires setup)

**Covered modules:**
- `connectors/` - Binance, Bybit WebSocket clients
- `database/` - PostgreSQL writer

## Configuration

### `pyproject.toml`

```toml
[tool.coverage.run]
omit = [
    "src/liquidity_monitor/connectors/*",  # Tested in integration
    "src/liquidity_monitor/database/*",    # Tested in integration
]

[tool.coverage.report]
fail_under = 85  # High bar for core logic only
show_missing = true
```

### Why This Works

1. **Core logic is deterministic** → Easy to test with 85%+ coverage
2. **Infrastructure is stateful** → Better tested with real systems
3. **CI stays green** → Fast, reliable builds
4. **Meaningful metrics** → Coverage reflects actual code quality

## Running Tests

```bash
# Run unit tests (fast, no external deps)
pytest tests/unit/ -v

# Run integration tests (requires API keys, slower)
pytest tests/integration/ -v -m integration

# Coverage report (core logic only)
pytest tests/unit/ --cov=src/liquidity_monitor --cov-report=term-missing
```

## Best Practices Applied

This approach follows industry standards from:
- **Jane Street** - Separate pure functions from I/O
- **Citadel** - Integration tests for market data pipelines
- **Two Sigma** - High coverage for quant logic, integration for infra

## Future Improvements

1. **Property-based testing** for OrderBook invariants (using Hypothesis)
2. **Mutation testing** to validate test quality (using mutmut)
3. **Benchmark tests** for performance regressions (using pytest-benchmark)

---

**Note**: This strategy prioritizes **code quality** over **vanity metrics**.
85% coverage of pure logic is more valuable than 50% coverage of everything.
