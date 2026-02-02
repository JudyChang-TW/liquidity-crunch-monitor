#!/usr/bin/env python3
"""
Multi-Exchange Order Book Demo

Demonstrates Feature A: Asynchronous Multi-Exchange Order Book Maintenance (L2 Data Reconstruction)

This example shows:
1. Concurrent WebSocket connections to Binance and Bybit
2. Real-time snapshot + delta update processing
3. Checksum verification for data integrity
4. Handling packet loss and reconnection
5. Cross-exchange spread comparison

Usage:
    python examples/multi_exchange_demo.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from liquidity_monitor.connectors.multi_exchange import MultiExchangeManager  # noqa: E402
from liquidity_monitor.utils.logger import configure_logging, get_logger  # noqa: E402

logger = get_logger(__name__)


async def demo_multi_exchange() -> None:
    """
    Demonstrate multi-exchange order book monitoring.

    This is the core implementation of Feature A:
    - Binance + Bybit concurrent WebSocket streams
    - Snapshot + delta update synchronization
    - Automatic reconnection with exponential backoff
    - Checksum validation (where available)
    """
    print("\n" + "=" * 80)
    print("🚀 MULTI-EXCHANGE ORDER BOOK DEMO".center(80))
    print("Feature A: Asynchronous Multi-Exchange Order Book Maintenance".center(80))
    print("=" * 80 + "\n")

    # Create multi-exchange manager
    manager = MultiExchangeManager(symbol="BTCUSDT", enable_binance=True, enable_bybit=True)

    print("📡 Connecting to exchanges...")
    print("   - Binance Futures WebSocket")
    print("   - Bybit Futures WebSocket")
    print("\n⏳ Waiting for order book synchronization...\n")

    # Start manager in background
    manager_task = asyncio.create_task(manager.run())

    try:
        # Wait for synchronization with timeout
        timeout = 30
        start_time = asyncio.get_event_loop().time()

        while not manager.is_all_synchronized():
            if asyncio.get_event_loop().time() - start_time > timeout:
                print("❌ Timeout waiting for synchronization")
                return

            await asyncio.sleep(0.5)

        print("✅ All exchanges synchronized!\n")

        # Display order books for 60 seconds
        iterations = 60
        for i in range(iterations):
            print("\n" + "=" * 80)
            print(f"📊 Order Book Snapshot #{i + 1}/{iterations}")
            print("=" * 80)

            # Get status from all exchanges
            status = manager.get_status()

            for exchange_name, exchange_status in status["exchanges"].items():
                print(f"\n🔷 {exchange_name.upper()}")
                print("-" * 40)

                orderbook_stats = exchange_status["orderbook_stats"]
                print(f"  Mid Price:     ${orderbook_stats['mid_price']:>12,.2f}")
                print(f"  Spread:        {orderbook_stats['spread_bps']:>12.2f} bps")
                print(f"  Bid Levels:    {orderbook_stats['bid_levels']:>12,}")
                print(f"  Ask Levels:    {orderbook_stats['ask_levels']:>12,}")
                print(f"  Messages:      {exchange_status['message_count']:>12,}")
                print(f"  Connected:     {exchange_status['is_synchronized']}")

                # Show checksum stats if available
                if "checksum_success_count" in exchange_status:
                    success = exchange_status["checksum_success_count"]
                    mismatch = exchange_status["checksum_mismatch_count"]
                    print(f"  Checksum OK:   {success:>12,}")
                    print(f"  Checksum Err:  {mismatch:>12,}")

            # Cross-exchange analysis
            print("\n🔀 CROSS-EXCHANGE ANALYSIS")
            print("-" * 40)

            spread_comparison = manager.get_spread_comparison()
            if spread_comparison:
                spreads = spread_comparison["spreads"]
                print(f"  Binance Spread: {spreads.get('binance', 0):.2f} bps")
                print(f"  Bybit Spread:   {spreads.get('bybit', 0):.2f} bps")
                print(f"  Difference:     {spread_comparison['spread_difference_bps']:.2f} bps")
                print(f"  Tightest:       {spread_comparison['tightest_exchange'].upper()}")

            arbitrage = manager.get_arbitrage_opportunities()
            if arbitrage and arbitrage.get("arbitrage_exists"):
                print("\n  💰 ARBITRAGE OPPORTUNITY DETECTED!")
                print(
                    f"     Buy from:  {arbitrage['buy_from'].upper()} @ ${arbitrage['buy_price']:,.2f}"
                )
                print(
                    f"     Sell to:   {arbitrage['sell_to'].upper()} @ ${arbitrage['sell_price']:,.2f}"
                )
                print(
                    f"     Profit:    ${arbitrage['spread_usd']:.2f} ({arbitrage['spread_bps']:.2f} bps)"
                )
            else:
                print("  ℹ️  No arbitrage opportunity")

            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")

    finally:
        print("\n🛑 Stopping manager...")
        manager.stop()
        await asyncio.sleep(2)  # Give time to cleanup
        manager_task.cancel()

        print("\n" + "=" * 80)
        print("📊 FINAL STATISTICS".center(80))
        print("=" * 80)

        final_status = manager.get_status()
        for exchange_name, exchange_status in final_status["exchanges"].items():
            print(f"\n{exchange_name.upper()}:")
            print(f"  Total Messages:  {exchange_status['message_count']:>10,}")
            print(f"  Reconnections:   {exchange_status['reconnect_count']:>10,}")
            if "checksum_success_count" in exchange_status:
                print(f"  Checksum Valid:  {exchange_status['checksum_success_count']:>10,}")
                print(f"  Checksum Errors: {exchange_status['checksum_mismatch_count']:>10,}")

        print("\n" + "=" * 80 + "\n")


async def demo_single_exchange(exchange: str = "binance") -> None:
    """
    Demonstrate single exchange monitoring with checksum validation.

    Args:
        exchange: "binance" or "bybit"
    """
    print("\n" + "=" * 80)
    print(f"🚀 SINGLE EXCHANGE DEMO - {exchange.upper()}".center(80))
    print("=" * 80 + "\n")

    if exchange == "binance":
        from liquidity_monitor.connectors.binance_futures import BinanceOrderBookManager

        manager = BinanceOrderBookManager(symbol="BTCUSDT")
    else:
        from liquidity_monitor.connectors.bybit_futures import BybitOrderBookManager

        manager = BybitOrderBookManager(symbol="BTCUSDT")

    print(f"📡 Connecting to {exchange.upper()}...")

    # Start manager in background
    manager_task = asyncio.create_task(manager.run())

    try:
        # Wait for synchronization
        timeout = 30
        start_time = asyncio.get_event_loop().time()

        while not manager.is_synchronized:
            if asyncio.get_event_loop().time() - start_time > timeout:
                print("❌ Timeout waiting for synchronization")
                return

            await asyncio.sleep(0.5)

        print("✅ Order book synchronized!\n")

        # Display order book for 30 seconds
        for i in range(30):
            status = manager.get_status()
            orderbook = manager.get_orderbook()

            best_bid = orderbook.get_best_bid()
            best_ask = orderbook.get_best_ask()

            print(f"\n[{i + 1}/30] Order Book Status:")
            print(
                f"  Best Bid: ${best_bid[0]:,.2f} x {best_bid[1]} BTC"
                if best_bid
                else "  Best Bid: N/A"
            )
            print(
                f"  Best Ask: ${best_ask[0]:,.2f} x {best_ask[1]} BTC"
                if best_ask
                else "  Best Ask: N/A"
            )
            print(
                f"  Spread:   {orderbook.get_spread_bps():.2f} bps"
                if orderbook.get_spread_bps()
                else "  Spread: N/A"
            )
            print(f"  Messages: {status['message_count']:,}")

            if exchange == "bybit" and "checksum_success_count" in status:
                print(f"  Checksum: ✅ {status['checksum_success_count']:,} valid")

            # Compute and display local checksum
            checksum = orderbook.compute_checksum(depth=10)
            print(f"  Local Checksum: {checksum}")

            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")

    finally:
        print("\n🛑 Stopping manager...")
        manager.stop()
        await asyncio.sleep(2)
        manager_task.cancel()


if __name__ == "__main__":
    # Configure logging
    configure_logging(log_level="INFO", json_format=False, colorize=True)

    print("\nSelect demo mode:")
    print("1. Multi-Exchange (Binance + Bybit) - Feature A Demo")
    print("2. Single Exchange - Binance")
    print("3. Single Exchange - Bybit")

    try:
        choice = input("\nEnter choice (1-3) [default: 1]: ").strip() or "1"

        if choice == "1":
            asyncio.run(demo_multi_exchange())
        elif choice == "2":
            asyncio.run(demo_single_exchange("binance"))
        elif choice == "3":
            asyncio.run(demo_single_exchange("bybit"))
        else:
            print("Invalid choice")

    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
