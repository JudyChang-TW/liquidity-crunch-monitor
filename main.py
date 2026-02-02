#!/usr/bin/env python3
"""
Liquidity-Crunch-Monitor - Main Entry Point

Real-time liquidity monitoring system for cryptocurrency futures markets.
Combines order book management, risk analytics, and anomaly detection.

Usage:
    python main.py
    python main.py --symbol ETHUSDT
    python main.py --symbol BTCUSDT --update-interval 0.5
"""

import argparse
import asyncio
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from liquidity_monitor.analytics.risk_engine import RiskEngine  # noqa: E402
from liquidity_monitor.connectors.binance_futures import BinanceOrderBookManager  # noqa: E402
from liquidity_monitor.connectors.multi_exchange import MultiExchangeManager  # noqa: E402
from liquidity_monitor.database import DatabaseWriter  # noqa: E402
from liquidity_monitor.utils.logger import configure_logging, get_logger  # noqa: E402

logger = get_logger(__name__)


class LiquidityMonitor:
    """
    Main application orchestrator for liquidity monitoring.

    Coordinates:
    - Order book manager (WebSocket)
    - Risk engine (analytics)
    - Console output (display)
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        update_interval: float = 1.0,
        slippage_sizes: Optional[List[float]] = None,
        enable_database: bool = True,
        db_host: str = "localhost",
        db_port: int = 5432,
        multi_exchange: bool = False,
        exchange: str = "binance",
    ):
        """
        Initialize liquidity monitor.

        Args:
            symbol: Trading pair to monitor
            update_interval: Seconds between metric updates
            slippage_sizes: List of order sizes (USD) to calculate slippage for
            enable_database: Enable PostgreSQL persistence
            db_host: PostgreSQL host
            db_port: PostgreSQL port
            multi_exchange: Enable multi-exchange mode (Binance + Bybit)
            exchange: Single exchange to monitor ("binance" or "bybit")
        """
        self.symbol = symbol
        self.update_interval = update_interval
        self.slippage_sizes = slippage_sizes or [100_000, 500_000, 1_000_000]
        self.enable_database = enable_database
        self.multi_exchange = multi_exchange
        self.exchange = exchange.lower()

        # Components
        if multi_exchange:
            self.manager: Any = MultiExchangeManager(symbol=symbol)
            self.primary_exchange = "binance"  # Use Binance as primary for metrics
        elif self.exchange == "bybit":
            from liquidity_monitor.connectors.bybit_futures import BybitOrderBookManager

            self.manager = BybitOrderBookManager(symbol=symbol)
            self.primary_exchange = "bybit"
        else:
            self.manager = BinanceOrderBookManager(symbol=symbol)
            self.primary_exchange = "binance"

        self.risk_engine: Optional[RiskEngine] = None
        self.db_writer: Optional[DatabaseWriter] = None

        # Database configuration
        if enable_database:
            # SECURITY: Fail Fast - No default password allowed
            # Production must set DB_PASSWORD environment variable
            db_password = os.getenv("DB_PASSWORD")

            if not db_password:
                logger.error(
                    "CRITICAL: DB_PASSWORD environment variable is not set. "
                    "For local development, create a .env.local file. "
                    "For production, configure secrets in your deployment platform."
                )
                sys.exit(1)  # Fail fast - force configuration before running

            self.db_writer = DatabaseWriter(
                password=db_password,
                host=db_host,
                port=db_port,
                database="liquidity_monitor",
                user="risk_analyst",
            )

        # Control flags
        self._should_stop = False
        self._is_initialized = False

        # Metrics tracking
        self.iteration = 0
        self.anomaly_count = 0
        self.snapshots_written = 0
        self.anomalies_written = 0

        logger.info(
            "liquidity_monitor_initialized",
            symbol=symbol,
            update_interval=update_interval,
            database_enabled=enable_database,
            multi_exchange=multi_exchange,
            exchange=self.primary_exchange,
        )

    def handle_shutdown(self, sig: signal.Signals) -> None:
        """Handle shutdown signal gracefully."""
        logger.info("shutdown_signal_received", signal=sig.name)
        self._should_stop = True
        self.manager.stop()

    async def wait_for_initialization(self) -> None:
        """Wait for order book to be synchronized and connect to database."""
        logger.info(
            "waiting_for_orderbook_sync", symbol=self.symbol, multi_exchange=self.multi_exchange
        )

        timeout = 30  # 30 second timeout
        start_time = asyncio.get_event_loop().time()

        while not self._should_stop:
            if self.multi_exchange:
                # Wait for all exchanges to sync
                is_synchronized = self.manager.is_all_synchronized()
            else:
                status = self.manager.get_status()
                is_synchronized = status["is_synchronized"]

            if is_synchronized:
                logger.info("orderbook_synchronized", symbol=self.symbol)

                # Get orderbook based on mode
                if self.multi_exchange:
                    orderbook = self.manager.get_orderbook(self.primary_exchange)
                else:
                    orderbook = self.manager.get_orderbook()

                # Initialize risk engine now that we have data
                self.risk_engine = RiskEngine(
                    orderbook=orderbook,
                    slippage_sizes_usd=self.slippage_sizes,
                    depth_bps=[10, 50, 100],
                    detector_window=300,
                    detector_threshold=3.0,
                )

                # Connect to database if enabled
                if self.enable_database and self.db_writer:
                    try:
                        await self.db_writer.connect()
                        logger.info("database_connected_successfully")
                    except Exception as e:
                        logger.warning(
                            "database_connection_failed",
                            error=str(e),
                            note="Continuing without database persistence",
                        )
                        self.enable_database = False
                        self.db_writer = None

                self._is_initialized = True
                break

            # Check timeout
            if asyncio.get_event_loop().time() - start_time > timeout:
                logger.error("initialization_timeout", timeout=timeout)
                raise TimeoutError("Order book synchronization timeout")

            await asyncio.sleep(0.5)

    def format_metrics_output(self, metrics: Dict[str, Any]) -> str:
        """
        Format metrics into clean, readable console output.

        Args:
            metrics: Metrics dictionary from RiskEngine

        Returns:
            Formatted string for console display
        """
        if "error" in metrics:
            return f"\n❌ Error: {metrics['error']}\n"

        basic = metrics["basic"]
        slippage = metrics["slippage"]
        depth = metrics["depth"]
        imbalance = metrics["imbalance"]
        anomaly = metrics["anomaly"]

        # Build output
        lines = []
        lines.append("\n" + "=" * 100)

        if self.multi_exchange:
            lines.append(
                f"🔍 MULTI-EXCHANGE LIQUIDITY MONITOR - {self.symbol} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Iteration #{self.iteration}"
            )
        else:
            lines.append(
                f"🔍 LIQUIDITY MONITOR [{self.primary_exchange.upper()}] - {self.symbol} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Iteration #{self.iteration}"
            )
        lines.append("=" * 100)

        # Basic metrics
        lines.append("\n📊 MARKET OVERVIEW:")
        lines.append(f"   Mid Price:     ${basic['mid_price']:>12,.2f}")
        lines.append(f"   Spread:        {basic['spread_bps']:>12.2f} bps")
        lines.append(f"   Bid Levels:    {basic['bid_levels']:>12,}")
        lines.append(f"   Ask Levels:    {basic['ask_levels']:>12,}")
        lines.append(
            f"   Imbalance:     {imbalance:>12.4f}  {'📈 Bullish' if imbalance > 0.2 else '📉 Bearish' if imbalance < -0.2 else '⚖️  Neutral'}"
        )

        # Depth metrics
        lines.append("\n💧 MARKET DEPTH:")
        for bps_key, depth_data in depth.items():
            total_usd = depth_data["total_depth_usd"]
            lines.append(
                f"   {bps_key:>6}:      ${total_usd:>12,.0f}  ({depth_data['total_depth']:.2f} BTC)"
            )

        # Slippage metrics
        lines.append("\n⚠️  SLIPPAGE ANALYSIS (Market Sell):")
        for size_key, slip_data in slippage.items():
            if "error" in slip_data:
                lines.append(f"   ${size_key:>8}: ERROR - {slip_data['error']}")
            else:
                size_label = size_key.replace("sell_", "$").replace("k", ",000")
                status_icon = "✅" if slip_data["filled"] else "❌"
                lines.append(
                    f"   {size_label:>10}: {slip_data['slippage_bps']:>8.2f} bps | "
                    f"${slip_data['slippage_usd']:>10,.0f} loss | "
                    f"{slip_data['levels_consumed']:>3} levels | {status_icon}"
                )

        # Anomaly detection
        lines.append("\n🚨 ANOMALY DETECTION:")

        if anomaly["is_anomaly"]:
            severity_icons = {
                "critical": "🔴 CRITICAL",
                "high": "🟠 HIGH",
                "warning": "🟡 WARNING",
                "none": "🟢 NORMAL",
            }
            severity_display = severity_icons.get(anomaly["severity"], anomaly["severity"])

            lines.append(f"   Status:        {severity_display}")
            lines.append(f"   Reason:        {anomaly['reason']}")
            lines.append(f"   Depth Z-Score: {anomaly['depth_zscore']:>8.2f}σ")
            lines.append(f"   Spread Z-Score:{anomaly['spread_zscore']:>8.2f}σ")
            lines.append(f"   Max Z-Score:   {anomaly['max_zscore']:>8.2f}σ")

            self.anomaly_count += 1
        else:
            lines.append("   Status:        🟢 NORMAL")
            lines.append(f"   Depth Z-Score: {anomaly['depth_zscore']:>8.2f}σ")
            lines.append(f"   Spread Z-Score:{anomaly['spread_zscore']:>8.2f}σ")

        # Statistics
        lines.append("\n📈 SESSION STATS:")
        lines.append(f"   Total Iterations:  {self.iteration:>8,}")
        lines.append(f"   Anomalies Detected:{self.anomaly_count:>8,}")

        if self.multi_exchange:
            status = self.manager.get_status()
            for exchange_name, exchange_status in status.get("exchanges", {}).items():
                msg_count = exchange_status.get("message_count", 0)
                lines.append(f"   {exchange_name.capitalize()} Messages: {msg_count:>8,}")
        else:
            lines.append(f"   Messages Processed:{self.manager.get_status()['message_count']:>8,}")

        # Latency monitoring (Feature C: HFT Performance Tracking)
        lines.append("\n📡 NETWORK LATENCY (Feature C):")

        if self.multi_exchange:
            status = self.manager.get_status()
            for exchange_name, exchange_status in status.get("exchanges", {}).items():
                latency_stats = exchange_status.get("latency_stats", {})
                if latency_stats and latency_stats.get("total_messages", 0) > 0:
                    current_ms = latency_stats.get("current_ms", 0.0)
                    avg_ms = latency_stats.get("average_ms", 0.0)
                    p99_ms = latency_stats.get("p99_ms", 0.0)
                    status_emoji = self._get_latency_emoji(latency_stats.get("status", "no_data"))

                    lines.append(f"\n   {exchange_name.capitalize()}:")
                    lines.append(f"     Current:   {current_ms:>8.2f} ms")
                    lines.append(f"     Average:   {avg_ms:>8.2f} ms")
                    lines.append(f"     P99:       {p99_ms:>8.2f} ms")
                    lines.append(
                        f"     Status:    {status_emoji} {latency_stats.get('status', 'unknown').upper()}"
                    )
        else:
            status = self.manager.get_status()
            latency_stats = status.get("latency_stats", {})
            if latency_stats and latency_stats.get("total_messages", 0) > 0:
                current_ms = latency_stats.get("current_ms", 0.0)
                avg_ms = latency_stats.get("average_ms", 0.0)
                p50_ms = latency_stats.get("p50_ms", 0.0)
                p95_ms = latency_stats.get("p95_ms", 0.0)
                p99_ms = latency_stats.get("p99_ms", 0.0)
                warning_count = latency_stats.get("warning_count", 0)
                critical_count = latency_stats.get("critical_count", 0)
                status_emoji = self._get_latency_emoji(latency_stats.get("status", "no_data"))

                lines.append(f"   Current:       {current_ms:>8.2f} ms")
                lines.append(f"   Average:       {avg_ms:>8.2f} ms")
                lines.append(f"   P50:           {p50_ms:>8.2f} ms")
                lines.append(f"   P95:           {p95_ms:>8.2f} ms")
                lines.append(f"   P99:           {p99_ms:>8.2f} ms")
                lines.append(
                    f"   Status:        {status_emoji} {latency_stats.get('status', 'unknown').upper()}"
                )

                if warning_count > 0 or critical_count > 0:
                    lines.append(f"   Warnings:      {warning_count:>8,}")
                    lines.append(f"   Critical:      {critical_count:>8,}")
            else:
                lines.append("   Status:        ⚪ Initializing...")

        # Database stats (if enabled)
        if self.enable_database:
            db_status = (
                "✅ Connected"
                if (self.db_writer and self.db_writer.is_connected())
                else "❌ Disconnected"
            )
            lines.append("\n💾 DATABASE:")
            lines.append(f"   Status:            {db_status}")
            lines.append(f"   Snapshots Written: {self.snapshots_written:>8,}")
            lines.append(f"   Anomalies Written: {self.anomalies_written:>8,}")

        lines.append("=" * 100 + "\n")

        return "\n".join(lines)

    def _get_latency_emoji(self, status: str) -> str:
        """
        Get emoji for latency status.

        Args:
            status: Latency status string

        Returns:
            Emoji representing latency status
        """
        emoji_map = {
            "excellent": "🟢",  # <10ms
            "good": "🟡",  # <50ms
            "warning": "🟠",  # <100ms
            "critical": "🔴",  # >=100ms
            "no_data": "⚪",
        }
        return emoji_map.get(status, "⚪")

    async def metrics_loop(self) -> None:
        """
        Main loop for calculating and displaying metrics.

        Runs every update_interval seconds and outputs formatted metrics.
        Also persists data to PostgreSQL if enabled.
        """
        logger.info("metrics_loop_started", interval=self.update_interval)

        # Wait for initialization
        await self.wait_for_initialization()

        logger.info("starting_metrics_output", symbol=self.symbol)

        # Main metrics loop
        while not self._should_stop:
            try:
                self.iteration += 1

                # Calculate metrics - check for None first (crash prevention)
                if self.risk_engine is None:
                    logger.error(
                        "risk_engine_not_initialized",
                        reason="Risk engine is None in metrics loop",
                        iteration=self.iteration,
                    )
                    await asyncio.sleep(1)
                    continue

                metrics = self.risk_engine.calculate_metrics()

                # Format and print to console
                output = self.format_metrics_output(metrics)
                print(output, flush=True)

                # Write to database (async, non-blocking)
                if self.enable_database and self.db_writer and self.db_writer.is_connected():
                    # Write snapshot every minute
                    if self.iteration % 60 == 0:  # Every 60 seconds
                        success = await self.db_writer.write_snapshot(
                            symbol=self.symbol, metrics=metrics
                        )
                        if success:
                            self.snapshots_written += 1

                    # Write anomaly if detected
                    anomaly = metrics.get("anomaly", {})
                    if anomaly.get("is_anomaly", False):
                        success = await self.db_writer.write_anomaly(
                            symbol=self.symbol, anomaly=anomaly, metrics=metrics
                        )
                        if success:
                            self.anomalies_written += 1

                # Wait for next iteration
                await asyncio.sleep(self.update_interval)

            except Exception as e:
                logger.error("metrics_loop_error", error=str(e), error_type=type(e).__name__)
                await asyncio.sleep(1)

        logger.info("metrics_loop_stopped")

    async def run(self) -> None:
        """
        Run the complete liquidity monitoring system.

        Coordinates:
        1. Order book manager (WebSocket)
        2. Metrics calculation and display loop
        """
        logger.info("starting_liquidity_monitor", symbol=self.symbol)

        try:
            # Run both components concurrently
            await asyncio.gather(
                self.manager.run(),  # Order book WebSocket
                self.metrics_loop(),  # Analytics and display
                return_exceptions=True,
            )

        except KeyboardInterrupt:
            logger.info("keyboard_interrupt")
        except Exception as e:
            logger.error("run_error", error=str(e), error_type=type(e).__name__)
        finally:
            self.manager.stop()

            # Close database connection
            if self.db_writer and self.db_writer.is_connected():
                await self.db_writer.close()

            logger.info("liquidity_monitor_stopped")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Liquidity-Crunch-Monitor - Real-time liquidity risk detection",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--symbol",
        "-s",
        type=str,
        default="BTCUSDT",
        help="Trading pair to monitor (e.g., BTCUSDT, ETHUSDT)",
    )

    parser.add_argument(
        "--update-interval", "-u", type=float, default=1.0, help="Seconds between metric updates"
    )

    parser.add_argument(
        "--slippage-sizes",
        type=str,
        default="100000,500000,1000000",
        help="Comma-separated list of order sizes (USD) for slippage calculation",
    )

    parser.add_argument(
        "--log-level",
        "-l",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    parser.add_argument("--json-logs", action="store_true", help="Output logs in JSON format")

    parser.add_argument("--log-file", type=str, help="Log to file (in addition to console)")

    parser.add_argument(
        "--no-database",
        action="store_true",
        help="Disable PostgreSQL persistence (console output only)",
    )

    parser.add_argument("--db-host", type=str, default="localhost", help="PostgreSQL host")

    parser.add_argument("--db-port", type=int, default=5432, help="PostgreSQL port")

    parser.add_argument(
        "--multi-exchange",
        action="store_true",
        help="Enable multi-exchange mode (monitor both Binance and Bybit)",
    )

    parser.add_argument(
        "--exchange",
        type=str,
        default="binance",
        choices=["binance", "bybit"],
        help="Single exchange to monitor (ignored if --multi-exchange is set)",
    )

    return parser.parse_args()


async def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Parse slippage sizes
    slippage_sizes = [float(x) for x in args.slippage_sizes.split(",")]

    # Configure logging
    configure_logging(log_level=args.log_level, json_format=args.json_logs, colorize=True)

    # Print banner
    print("\n" + "=" * 100)
    if args.multi_exchange:
        print("🔍 MULTI-EXCHANGE LIQUIDITY-CRUNCH-MONITOR".center(100))
        print("Concurrent Binance + Bybit Order Book Monitoring".center(100))
    else:
        print("🔍 LIQUIDITY-CRUNCH-MONITOR".center(100))
        print("Real-Time Liquidity Risk Detection for Cryptocurrency Futures".center(100))
    print("=" * 100)
    print(f"\n📊 Monitoring: {args.symbol}")
    if args.multi_exchange:
        print("🔄 Mode: Multi-Exchange (Binance + Bybit)")
    else:
        print(f"🔄 Mode: Single Exchange ({args.exchange.upper()})")
    print(f"⏱️  Update Interval: {args.update_interval}s")
    print(f"💰 Slippage Sizes: {', '.join([f'${int(s):,}' for s in slippage_sizes])}")
    print(f"📝 Log Level: {args.log_level}")
    print(
        f"💾 Database: {'Disabled' if args.no_database else f'Enabled ({args.db_host}:{args.db_port})'}"
    )
    print("\n" + "=" * 100)
    print("\n🚀 Starting monitoring... (Press Ctrl+C to stop)\n")

    logger.info(
        "liquidity_monitor_starting",
        version="0.1.0",
        symbol=args.symbol,
        update_interval=args.update_interval,
        slippage_sizes=slippage_sizes,
    )

    # Create and run monitor
    monitor = LiquidityMonitor(
        symbol=args.symbol,
        update_interval=args.update_interval,
        slippage_sizes=slippage_sizes,
        enable_database=not args.no_database,
        db_host=args.db_host,
        db_port=args.db_port,
        multi_exchange=args.multi_exchange,
        exchange=args.exchange,
    )

    # Setup signal handlers
    loop = asyncio.get_event_loop()

    def make_handler(sig: signal.Signals) -> Any:
        """Create signal handler closure."""
        return lambda: monitor.handle_shutdown(sig)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, make_handler(sig))

    # Run monitor
    try:
        await monitor.run()
    finally:
        print("\n" + "=" * 100)
        print("👋 Liquidity Monitor Stopped".center(100))
        print(f"Total Iterations: {monitor.iteration}".center(100))
        print(f"Anomalies Detected: {monitor.anomaly_count}".center(100))
        if monitor.enable_database:
            print(f"Snapshots Written: {monitor.snapshots_written}".center(100))
            print(f"Anomalies Written: {monitor.anomalies_written}".center(100))
        print("=" * 100 + "\n")
        logger.info("liquidity_monitor_stopped")


if __name__ == "__main__":
    # Use uvloop if available for better performance
    try:
        import uvloop

        uvloop.install()
        print("✅ uvloop enabled (2-4x performance boost)")
    except ImportError:
        print("⚠️  uvloop not available - install for better performance: pip install uvloop")

    # Run application
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")
        sys.exit(0)
