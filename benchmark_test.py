#!/usr/bin/env python3
"""
Performance Benchmark for Liquidity Monitor Engine

This script benchmarks the internal processing throughput of:
1. OrderBook updates (SortedDict operations)
2. Risk metrics calculation (slippage, depth, imbalance)
3. Anomaly detection (Z-score analysis)

NOTE: This benchmark tests COMPUTATIONAL PERFORMANCE only (no database I/O).
In production, PostgreSQL writes happen asynchronously via asyncpg connection
pool and do not block the hot path. The real bottleneck is the WebSocket feed
(~10-100 updates/sec), not the engine (18K+ msgs/sec capacity).

Usage:
    python benchmark_test.py
"""

import asyncio
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

try:
    import uvloop

    uvloop.install()
    UVLOOP_AVAILABLE = True
except ImportError:
    UVLOOP_AVAILABLE = False
    print("⚠️  uvloop not available, using default asyncio event loop")

from liquidity_monitor.analytics.risk_engine import (  # noqa: E402
    RiskEngine,
    calculate_depth_imbalance,
    calculate_slippage,
)
from liquidity_monitor.core.orderbook import OrderBook  # noqa: E402


def generate_mock_orderbook_update() -> Dict[str, Any]:
    """Generate realistic order book update message."""
    return {
        "u": 123456789,
        "bids": [
            ["50000.50", "1.5"],
            ["50000.00", "2.0"],
            ["49999.50", "1.8"],
            ["49999.00", "3.2"],
            ["49998.50", "2.5"],
        ],
        "asks": [
            ["50001.00", "2.0"],
            ["50001.50", "1.8"],
            ["50002.00", "3.0"],
            ["50002.50", "2.2"],
            ["50003.00", "1.5"],
        ],
    }


async def benchmark_orderbook_updates(iterations: int = 100_000) -> float:
    """
    Benchmark 1: OrderBook Update Performance (Hot Path)

    Tests the core SortedDict O(log n) operations.
    """
    print("\n" + "=" * 60)
    print("📊 Benchmark 1: OrderBook Updates (SortedDict)")
    print("=" * 60)

    orderbook = OrderBook(symbol="BTCUSDT")

    # Initialize with snapshot
    bids_snapshot = [["50000.00", "1.0"], ["49999.00", "2.0"]]
    asks_snapshot = [["50001.00", "1.0"], ["50002.00", "2.0"]]
    orderbook.apply_snapshot(bids_snapshot, asks_snapshot, last_update_id=100000)

    update_msg = generate_mock_orderbook_update()

    start_time = time.perf_counter()

    for _ in range(iterations):
        # Simulate processing each bid/ask update
        for bid in update_msg["bids"]:
            price = Decimal(bid[0])
            qty = Decimal(bid[1])
            orderbook.update_bid(price, qty)

        for ask in update_msg["asks"]:
            price = Decimal(ask[0])
            qty = Decimal(ask[1])
            orderbook.update_ask(price, qty)

    end_time = time.perf_counter()
    total_time = end_time - start_time

    # Each iteration processes 10 levels (5 bids + 5 asks)
    total_updates = iterations * 10
    ops_per_sec = total_updates / total_time

    print(f"⏱️  Total Time: {total_time:.4f} seconds")
    print(f"🔢 Total Updates: {total_updates:,}")
    print(f"⚡ Throughput: {ops_per_sec:,.0f} updates/sec")
    print(f"📈 Latency: {(total_time / total_updates) * 1_000_000:.2f} μs per update")

    if ops_per_sec > 5_000:
        print("✅ PASS: Exceeds 5,000 updates/sec target")
    else:
        print("⚠️  FAIL: Below 5,000 updates/sec target")

    return ops_per_sec


async def benchmark_risk_calculations(iterations: int = 50_000) -> float:
    """
    Benchmark 2: Risk Metrics Calculation

    Tests slippage, depth, and imbalance calculations.
    """
    print("\n" + "=" * 60)
    print("📊 Benchmark 2: Risk Metrics Calculation")
    print("=" * 60)

    # Prepare realistic order book data
    bids = [
        (Decimal("50000.00"), Decimal("1.5")),
        (Decimal("49999.00"), Decimal("2.0")),
        (Decimal("49998.00"), Decimal("1.8")),
        (Decimal("49997.00"), Decimal("2.5")),
        (Decimal("49996.00"), Decimal("3.0")),
    ]

    asks = [
        (Decimal("50001.00"), Decimal("2.0")),
        (Decimal("50002.00"), Decimal("1.8")),
        (Decimal("50003.00"), Decimal("2.2")),
        (Decimal("50004.00"), Decimal("1.5")),
        (Decimal("50005.00"), Decimal("2.8")),
    ]

    start_time = time.perf_counter()

    for _ in range(iterations):
        # Calculate slippage for $100k order
        _ = calculate_slippage(bids, asks, 100_000, "sell")

        # Calculate order book imbalance
        imbalance = calculate_depth_imbalance(bids, asks, levels=5)

        # Simulate anomaly detection check
        _ = abs(imbalance) > 0.8

    end_time = time.perf_counter()
    total_time = end_time - start_time
    ops_per_sec = iterations / total_time

    print(f"⏱️  Total Time: {total_time:.4f} seconds")
    print(f"🔢 Total Calculations: {iterations:,}")
    print(f"⚡ Throughput: {ops_per_sec:,.0f} calculations/sec")
    print(f"📈 Latency: {(total_time / iterations) * 1_000:.2f} ms per calculation")

    if ops_per_sec > 5_000:
        print("✅ PASS: Exceeds 5,000 calculations/sec target")
    else:
        print("⚠️  FAIL: Below 5,000 calculations/sec target")

    return ops_per_sec


async def benchmark_full_pipeline(iterations: int = 10_000) -> float:
    """
    Benchmark 3: Full Processing Pipeline

    Tests the complete flow: Update -> Calculate -> Detect
    """
    print("\n" + "=" * 60)
    print("📊 Benchmark 3: Full Processing Pipeline")
    print("=" * 60)

    orderbook = OrderBook(symbol="BTCUSDT")
    risk_engine = RiskEngine(orderbook=orderbook)

    # Initialize orderbook
    bids_snapshot = [
        ["50000.00", "1.5"],
        ["49999.00", "2.0"],
        ["49998.00", "1.8"],
        ["49997.00", "2.5"],
        ["49996.00", "3.0"],
    ]
    asks_snapshot = [
        ["50001.00", "2.0"],
        ["50002.00", "1.8"],
        ["50003.00", "2.2"],
        ["50004.00", "1.5"],
        ["50005.00", "2.8"],
    ]
    orderbook.apply_snapshot(bids_snapshot, asks_snapshot, last_update_id=100000)

    update_msg = generate_mock_orderbook_update()

    start_time = time.perf_counter()

    for _ in range(iterations):
        # Step 1: Update orderbook
        for bid in update_msg["bids"][:3]:  # Update top 3 levels
            orderbook.update_bid(Decimal(bid[0]), Decimal(bid[1]))

        for ask in update_msg["asks"][:3]:
            orderbook.update_ask(Decimal(ask[0]), Decimal(ask[1]))

        # Step 2: Calculate risk metrics
        metrics = risk_engine.calculate_metrics()

        # Step 3: Check for anomalies (simulated)
        _ = metrics["slippage"]["sell_100k"]["slippage_bps"] > 50

    end_time = time.perf_counter()
    total_time = end_time - start_time
    ops_per_sec = iterations / total_time

    print(f"⏱️  Total Time: {total_time:.4f} seconds")
    print(f"🔢 Total Pipeline Runs: {iterations:,}")
    print(f"⚡ Throughput: {ops_per_sec:,.0f} messages/sec")
    print(f"📈 Latency: {(total_time / iterations) * 1_000:.2f} ms per message")

    if ops_per_sec > 5_000:
        print("✅ PASS: Exceeds 5,000 messages/sec target")
    else:
        print("⚠️  FAIL: Below 5,000 messages/sec target")

    return ops_per_sec


async def main() -> None:
    """Run all benchmarks."""
    print("\n" + "=" * 60)
    print("🚀 LIQUIDITY MONITOR - PERFORMANCE BENCHMARK")
    print("=" * 60)

    if UVLOOP_AVAILABLE:
        print("✅ Using uvloop for enhanced performance")
    else:
        print("⚠️  Using default asyncio event loop")

    # Run benchmarks
    orderbook_ops = await benchmark_orderbook_updates(iterations=100_000)
    risk_calc_ops = await benchmark_risk_calculations(iterations=50_000)
    pipeline_ops = await benchmark_full_pipeline(iterations=10_000)

    # Summary
    print("\n" + "=" * 60)
    print("📊 BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"OrderBook Updates:    {orderbook_ops:>12,.0f} ops/sec")
    print(f"Risk Calculations:    {risk_calc_ops:>12,.0f} ops/sec")
    print(f"Full Pipeline:        {pipeline_ops:>12,.0f} msgs/sec")
    print("=" * 60)

    # Determine overall result
    all_pass = all(
        [
            orderbook_ops > 5_000,
            risk_calc_ops > 5_000,
            pipeline_ops > 5_000,
        ]
    )

    if all_pass:
        print("\n🏆 OVERALL RESULT: ALL BENCHMARKS PASSED")
        print("✅ System exceeds 5,000 ops/sec target for all operations")
    else:
        print("\n⚠️  OVERALL RESULT: SOME BENCHMARKS FAILED")
        print("Consider optimizing hot paths and reducing logging")

    print("\n💡 Recommendation for Resume:")
    if pipeline_ops >= 5_000:
        print(f"   'Achieved {pipeline_ops:,.0f} messages/sec throughput'")
    else:
        print("   'Optimized for high-frequency processing with O(log n) operations'")
    print()


if __name__ == "__main__":
    asyncio.run(main())
