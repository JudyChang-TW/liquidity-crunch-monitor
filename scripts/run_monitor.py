#!/usr/bin/env python3
"""
CLI entry point for Liquidity-Crunch-Monitor.

This script initializes and runs the Binance Order Book Manager,
monitoring real-time liquidity for specified symbols.

Usage:
    python scripts/run_monitor.py --symbol BTCUSDT
    python scripts/run_monitor.py --symbol ETHUSDT --log-level DEBUG
"""

import argparse
import asyncio
import signal
import sys
from pathlib import Path
from typing import List

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from liquidity_monitor.connectors.binance_futures import BinanceOrderBookManager  # noqa: E402
from liquidity_monitor.utils.logger import configure_logging, get_logger  # noqa: E402

logger = get_logger(__name__)


class MonitorApp:
    """
    Main application for monitoring liquidity.

    Handles multiple symbols, graceful shutdown, and status reporting.
    """

    def __init__(
        self,
        symbols: List[str],
        ws_url: str = "wss://fstream.binance.com/ws",
        rest_url: str = "https://fapi.binance.com",
    ):
        """
        Initialize monitor application.

        Args:
            symbols: List of symbols to monitor (e.g., ["BTCUSDT", "ETHUSDT"])
            ws_url: WebSocket base URL
            rest_url: REST API base URL
        """
        self.symbols = symbols
        self.ws_url = ws_url
        self.rest_url = rest_url

        # Create manager for each symbol
        self.managers: List[BinanceOrderBookManager] = []
        for symbol in symbols:
            manager = BinanceOrderBookManager(symbol=symbol, ws_url=ws_url, rest_url=rest_url)
            self.managers.append(manager)

        # Shutdown flag
        self._should_stop = False

        logger.info("app_initialized", symbols=symbols, manager_count=len(self.managers))

    def handle_shutdown(self, sig: signal.Signals) -> None:
        """
        Handle shutdown signals gracefully.

        Args:
            sig: Signal received (SIGINT or SIGTERM)
        """
        logger.info("shutdown_signal_received", signal=sig.name)
        self._should_stop = True

        # Stop all managers
        for manager in self.managers:
            manager.stop()

    async def print_status(self) -> None:
        """Periodically print status of all managers."""
        while not self._should_stop:
            await asyncio.sleep(10)  # Print every 10 seconds

            logger.info("=" * 80)
            logger.info("status_report", timestamp=asyncio.get_event_loop().time())

            for manager in self.managers:
                status = manager.get_status()
                logger.info("manager_status", **status)

            logger.info("=" * 80)

    async def run(self) -> None:
        """
        Run the monitoring application.

        Starts all managers concurrently and monitors their status.
        """
        logger.info("starting_application")

        try:
            # Create tasks for all managers
            manager_tasks = [asyncio.create_task(manager.run()) for manager in self.managers]

            # Create status reporting task
            status_task = asyncio.create_task(self.print_status())

            # Wait for all tasks
            await asyncio.gather(*manager_tasks, status_task, return_exceptions=True)

        except KeyboardInterrupt:
            logger.info("keyboard_interrupt_received")
        except Exception as e:
            logger.error("application_error", error=str(e), error_type=type(e).__name__)
        finally:
            logger.info("application_shutting_down")

            # Stop all managers
            for manager in self.managers:
                manager.stop()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Liquidity-Crunch-Monitor - Real-time order book monitoring",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--symbol",
        "-s",
        type=str,
        action="append",
        default=[],
        help="Symbol to monitor (can specify multiple times, e.g., -s BTCUSDT -s ETHUSDT)",
    )

    parser.add_argument(
        "--log-level",
        "-l",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level",
    )

    parser.add_argument("--json-logs", action="store_true", help="Output logs in JSON format")

    parser.add_argument("--no-color", action="store_true", help="Disable colored output")

    parser.add_argument(
        "--ws-url", type=str, default="wss://fstream.binance.com/ws", help="Binance WebSocket URL"
    )

    parser.add_argument(
        "--rest-url", type=str, default="https://fapi.binance.com", help="Binance REST API URL"
    )

    args = parser.parse_args()

    # Default to BTCUSDT if no symbols specified
    if not args.symbol:
        args.symbol = ["BTCUSDT"]

    return args


async def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Configure logging
    configure_logging(
        log_level=args.log_level, json_format=args.json_logs, colorize=not args.no_color
    )

    logger.info(
        "liquidity_monitor_starting", version="0.1.0", symbols=args.symbol, log_level=args.log_level
    )

    # Create and run application
    app = MonitorApp(symbols=args.symbol, ws_url=args.ws_url, rest_url=args.rest_url)

    # Setup signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: app.handle_shutdown(s))

    # Run application
    try:
        await app.run()
    finally:
        logger.info("liquidity_monitor_stopped")


if __name__ == "__main__":
    # Use uvloop if available for better performance
    try:
        import uvloop

        uvloop.install()
        logger.info("uvloop_enabled")
    except ImportError:
        logger.warning("uvloop_not_available", message="Install uvloop for better performance")

    # Run application
    asyncio.run(main())
