#!/usr/bin/env python3
"""
Simple example demonstrating BinanceOrderBookManager usage.

This example shows how to:
1. Initialize the manager
2. Connect to WebSocket
3. Monitor order book updates
4. Access order book data

Run:
    python examples/simple_example.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from liquidity_monitor.connectors.binance_futures import BinanceOrderBookManager  # noqa: E402
from liquidity_monitor.utils.logger import configure_logging, get_logger  # noqa: E402

# Configure logging
configure_logging(log_level="INFO", json_format=False, colorize=True)
logger = get_logger(__name__)


async def monitor_orderbook(symbol: str = "BTCUSDT", duration: int = 30) -> None:
    """
    Monitor order book for specified duration.

    Args:
        symbol: Trading pair to monitor
        duration: How long to monitor (seconds)
    """
    # Create manager
    manager = BinanceOrderBookManager(symbol=symbol)

    logger.info(f"Starting to monitor {symbol} for {duration} seconds...")

    # Start manager in background
    manager_task = asyncio.create_task(manager.run())

    try:
        # Monitor for specified duration
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < duration:
            await asyncio.sleep(5)  # Check every 5 seconds

            # Get current status
            status = manager.get_status()

            # Get order book stats
            orderbook = manager.get_orderbook()
            stats = orderbook.get_stats()

            # Get current depth (top 5 levels)
            depth = orderbook.get_depth(levels=5)

            # Print summary
            logger.info("=" * 80)
            logger.info(f"Symbol: {symbol}")
            logger.info(f"Connected: {status['is_connected']}")
            logger.info(f"Synchronized: {status['is_synchronized']}")
            logger.info(f"Messages processed: {status['message_count']}")
            logger.info(f"Last update ID: {stats['last_update_id']}")
            logger.info("")
            logger.info(f"Mid Price: ${stats['mid_price']:,.2f}")
            logger.info(f"Spread: {stats['spread_bps']:.2f} bps")
            logger.info(f"Bid Levels: {stats['bid_levels']}")
            logger.info(f"Ask Levels: {stats['ask_levels']}")
            logger.info("")
            logger.info("Top 5 Bids:")
            for price, qty in depth["bids"][:5]:
                logger.info(f"  ${float(price):,.2f} × {float(qty):.4f} BTC")
            logger.info("")
            logger.info("Top 5 Asks:")
            for price, qty in depth["asks"][:5]:
                logger.info(f"  ${float(price):,.2f} × {float(qty):.4f} BTC")
            logger.info("=" * 80)

    finally:
        # Stop manager gracefully
        manager.stop()
        await manager_task
        logger.info("Monitor stopped")


async def main() -> None:
    """Main entry point."""
    try:
        # Use uvloop if available
        try:
            import uvloop

            uvloop.install()
            logger.info("Using uvloop for enhanced performance")
        except ImportError:
            logger.warning("uvloop not available - install for better performance")

        # Monitor BTCUSDT for 30 seconds
        await monitor_orderbook("BTCUSDT", duration=30)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
