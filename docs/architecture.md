# System Architecture

## Overview

Liquidity-Crunch-Monitor is designed as an **event-driven, asynchronous system** optimized for low-latency processing of high-frequency market data.

## Component Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                     Application Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │  CLI Entry   │  │  REST API    │  │  Dashboard   │        │
│  │   Point      │  │  (Optional)  │  │  (Optional)  │        │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘        │
└─────────┼──────────────────┼──────────────────┼────────────────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │
┌────────────────────────────┼────────────────────────────────────┐
│                      Core Engine                                │
│                             │                                   │
│  ┌─────────────────────────▼───────────────────────────┐       │
│  │           Event Loop Orchestrator                   │       │
│  │         (uvloop-powered asyncio)                    │       │
│  └─────────────────────────┬───────────────────────────┘       │
│                             │                                   │
│  ┌────────────┬─────────────┼─────────────┬─────────────┐      │
│  │            │             │             │             │      │
│  ▼            ▼             ▼             ▼             ▼      │
│ ┌──────┐  ┌────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
│ │ WS   │  │OrderBook│ │ Metrics │ │ Anomaly │ │ Alert   │  │
│ │Conn. │─▶│ Engine  │─▶│Calculator│─▶│Detector │─▶│ Manager │  │
│ └──────┘  └────────┘  └─────────┘  └─────────┘  └─────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
          │            │            │            │
          ▼            ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Data Layer                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ SortedDict│ │ numpy    │ │ InfluxDB │ │ Redis    │       │
│  │ (In-Mem) │ │ Arrays   │ │(TimeSeries)│(Distributed)│       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. WebSocket Connection Lifecycle

```
[Start] ─▶ [Connect] ─▶ [Authenticate] ─▶ [Subscribe] ─▶ [Listen]
                │                              │            │
                │                              │            ▼
                │                              │       [Process Update]
                │                              │            │
                ▼                              ▼            ▼
           [Reconnect] ◀───── [Disconnected] ◀──── [Error/Timeout]
                │
                └──▶ [Exponential Backoff] ─▶ [Connect]
```

### 2. Order Book Update Processing

```
WebSocket Message
       │
       ▼
[Parse JSON]
       │
       ▼
[Validate Update ID]
       │
       ├─▶ [Out of Sequence?] ─▶ [Request Snapshot]
       │                                │
       │                                ▼
       │                         [Rebuild Book]
       │                                │
       └────────────────────────────────┘
                      │
                      ▼
           [Apply Updates to SortedDict]
                      │
              ┌───────┴───────┐
              ▼               ▼
         [Update Bids]   [Update Asks]
              │               │
              └───────┬───────┘
                      ▼
            [Calculate Metrics]
                      │
              ┌───────┴───────┐
              ▼               ▼
        [Liquidity]      [Anomaly]
         [Metrics]       [Detection]
```

## Concurrency Model

### asyncio Event Loop

```python
# Main event loop structure
async def main():
    """
    Single-threaded event loop managing multiple coroutines.
    """
    # Replace default event loop with uvloop
    if USE_UVLOOP:
        uvloop.install()

    async with asyncio.TaskGroup() as tg:
        # Spawn independent coroutines
        tg.create_task(websocket_connector.run())
        tg.create_task(orderbook_engine.process_queue())
        tg.create_task(metrics_calculator.calculate_loop())
        tg.create_task(anomaly_detector.detect_loop())
        tg.create_task(health_check_server.serve())
```

### Message Passing via Queues

```
┌────────────┐         ┌────────────┐         ┌────────────┐
│  WebSocket │ ──────▶ │  OrderBook │ ──────▶ │  Metrics   │
│  Connector │  Queue1 │   Engine   │  Queue2 │ Calculator │
└────────────┘         └────────────┘         └────────────┘
     │                                               │
     │ asyncio.Queue                                 │ asyncio.Queue
     │ (bounded, backpressure)                       │
     ▼                                               ▼
[Raw Updates]                                  [Book Snapshots]
```

## Performance Optimizations

### 1. **Order Book Storage: SortedDict**

```python
from sortedcontainers import SortedDict

class OrderBookSide:
    def __init__(self):
        self.levels: SortedDict[Decimal, Decimal] = SortedDict()

    def update(self, price: Decimal, qty: Decimal) -> None:
        """O(log n) insertion/update"""
        if qty == 0:
            self.levels.pop(price, None)  # O(log n) deletion
        else:
            self.levels[price] = qty  # O(log n) insert/update

    def get_best(self, side: str) -> tuple[Decimal, Decimal]:
        """O(1) best bid/ask access"""
        if side == "bid":
            return self.levels.peekitem(-1)  # Last item (highest bid)
        else:
            return self.levels.peekitem(0)   # First item (lowest ask)
```

**Complexity Analysis:**
- Insert/Update: O(log n)
- Delete: O(log n)
- Best price access: O(1)
- Iteration: O(k) for k levels

### 2. **Batch Processing**

```python
async def process_updates_batch(updates: list[dict]) -> None:
    """
    Process multiple updates in one pass to amortize overhead.
    """
    for update in updates:
        orderbook.apply_update(update)  # O(log n) per update

    # Calculate metrics once for entire batch
    metrics = calculate_liquidity_metrics(orderbook)  # O(k)
```

**Benefit**: Reduces function call overhead and improves CPU cache locality.

### 3. **Decimal Arithmetic**

```python
from decimal import Decimal

# Avoid floating-point precision issues
price = Decimal("19567.30")  # Exact representation
quantity = Decimal("1.5")

# All arithmetic is exact
total = price * quantity  # Decimal("29350.950")
```

**Why not float?**
```python
# Float precision errors compound in HFT
0.1 + 0.2 == 0.3  # False! (0.30000000000000004)
```

## Error Handling & Resilience

### WebSocket Disconnection Strategy

```python
class ResilientWebSocket:
    async def maintain_connection(self) -> None:
        reconnect_delay = 2  # Start with 2 seconds

        while True:
            try:
                await self._connect()
                reconnect_delay = 2  # Reset on success
                await self._listen()
            except WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)  # Cap at 60s
```

### Order Book Synchronization

```python
async def synchronize_orderbook(self) -> None:
    """
    Ensure local order book matches exchange state after reconnection.
    """
    # Step 1: Buffer incoming updates
    buffer = []

    # Step 2: Fetch snapshot via REST
    snapshot = await self.fetch_snapshot()

    # Step 3: Filter buffered updates
    valid_updates = [
        u for u in buffer
        if u['lastUpdateId'] > snapshot['lastUpdateId']
    ]

    # Step 4: Rebuild and apply
    orderbook.rebuild_from_snapshot(snapshot)
    for update in valid_updates:
        orderbook.apply_update(update)
```

## Scalability Considerations

### Horizontal Scaling (Future)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Monitor 1  │     │  Monitor 2  │     │  Monitor 3  │
│  (BTCUSDT)  │     │  (ETHUSDT)  │     │  (BNBUSDT)  │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                    ┌──────▼──────┐
                    │    Redis    │
                    │  (Pub/Sub)  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Aggregator │
                    └─────────────┘
```

### Vertical Scaling Limits

Current single-process design can handle:
- **10-20 symbols** simultaneously (@ 100ms update speed)
- **50,000+ updates/sec** total throughput
- **<50MB RAM** per symbol

**Bottleneck**: GIL for CPU-intensive metrics calculation
**Solution**: Offload heavy computation to Rust/C++ extensions

## Monitoring & Observability

### Key Performance Indicators (KPIs)

```python
@dataclass
class SystemMetrics:
    # Latency (microseconds)
    ws_message_latency_p50: float
    ws_message_latency_p99: float
    orderbook_update_latency: float
    metrics_calculation_latency: float

    # Throughput
    messages_per_second: int
    updates_per_second: int

    # System health
    websocket_connected: bool
    queue_depth: int
    memory_usage_mb: float
    cpu_usage_percent: float
```

### Health Check Endpoint

```python
@app.get("/health")
async def health_check():
    return {
        "status": "healthy" if ws_connected else "degraded",
        "uptime_seconds": time.time() - start_time,
        "last_message_age_ms": (time.time() - last_msg_time) * 1000,
        "queue_depth": message_queue.qsize(),
    }
```

## Security Considerations

1. **No API Keys in Code**: Use environment variables
2. **WebSocket Authentication**: Optional for public streams, required for private
3. **Rate Limiting**: Respect exchange rate limits (avoid IP bans)
4. **Input Validation**: Sanitize all WebSocket messages
5. **Secrets Management**: Use `python-dotenv` or cloud secret managers

## Testing Strategy

### Unit Tests
- Mock WebSocket responses
- Test order book operations in isolation
- Validate metric calculations with known inputs

### Integration Tests
- Connect to Binance testnet WebSocket
- Verify end-to-end data flow
- Test reconnection logic

### Load Tests
- Simulate 50K updates/sec using locust
- Measure latency under stress
- Identify memory leaks

## Future Enhancements

1. **Multi-Exchange Support**: OKX, Bybit, Kraken
2. **Machine Learning**: LSTM for liquidity prediction
3. **Distributed Architecture**: Multi-process with Redis
4. **GPU Acceleration**: CUDA for metric calculation
5. **Low-Latency C++ Core**: Python bindings for hot paths
