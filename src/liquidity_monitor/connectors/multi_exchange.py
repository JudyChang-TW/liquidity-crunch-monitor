"""
Multi-Exchange Manager for concurrent order book monitoring.

This module provides a unified interface to monitor order books across
multiple exchanges simultaneously (Binance + Bybit).

This demonstrates the ability to handle:
- Concurrent WebSocket connections to multiple exchanges
- Different API protocols and message formats
- Unified order book data access
- Cross-exchange arbitrage detection (future enhancement)
"""

import asyncio
from typing import Any, Dict, List, Optional, Union

from ..core.orderbook import OrderBook
from ..utils.logger import get_logger
from .binance_futures import BinanceOrderBookManager
from .bybit_futures import BybitOrderBookManager

logger = get_logger(__name__)


class MultiExchangeManager:
    """
    Manages order book synchronization across multiple exchanges.

    This is the key component that demonstrates Feature A:
    Asynchronous Multi-Exchange Order Book Maintenance (L2 Data Reconstruction)

    Attributes:
        symbol: Trading pair symbol (e.g., "BTCUSDT")
        exchanges: Dictionary of exchange managers
        is_running: Whether the manager is currently running

    Example:
        >>> manager = MultiExchangeManager("BTCUSDT")
        >>> await manager.run()
        >>> binance_book = manager.get_orderbook("binance")
        >>> bybit_book = manager.get_orderbook("bybit")
    """

    def __init__(
        self,
        symbol: str,
        enable_binance: bool = True,
        enable_bybit: bool = True,
    ):
        """
        Initialize Multi-Exchange Manager.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            enable_binance: Enable Binance monitoring
            enable_bybit: Enable Bybit monitoring
        """
        self.symbol = symbol.upper()
        self.enable_binance = enable_binance
        self.enable_bybit = enable_bybit

        # Exchange managers
        self.exchanges: Dict[str, Union[BinanceOrderBookManager, BybitOrderBookManager]] = {}

        if enable_binance:
            self.exchanges["binance"] = BinanceOrderBookManager(symbol=symbol)
            logger.info("binance_manager_added", symbol=symbol)

        if enable_bybit:
            self.exchanges["bybit"] = BybitOrderBookManager(symbol=symbol)
            logger.info("bybit_manager_added", symbol=symbol)

        # Control flags
        self.is_running: bool = False
        self._should_stop: bool = False
        self._tasks: List[asyncio.Task[None]] = []

        logger.info(
            "multi_exchange_manager_initialized",
            symbol=symbol,
            exchanges=list(self.exchanges.keys()),
        )

    async def run(self) -> None:
        """
        Run all exchange managers concurrently.

        This method launches WebSocket connections to all enabled exchanges
        and monitors them simultaneously using asyncio.gather().

        This is the core of Feature A - demonstrating:
        1. Concurrent WebSocket management
        2. Independent order book synchronization
        3. Automatic reconnection per exchange
        """
        logger.info(
            "starting_multi_exchange_manager",
            symbol=self.symbol,
            exchanges=list(self.exchanges.keys()),
        )

        self.is_running = True

        try:
            # Launch all exchange managers concurrently
            tasks = []
            for exchange_name, manager in self.exchanges.items():
                task = asyncio.create_task(manager.run())
                task.set_name(f"{exchange_name}_{self.symbol}")
                tasks.append(task)
                self._tasks.append(task)

                logger.info("exchange_task_started", exchange=exchange_name, symbol=self.symbol)

            # Wait for all tasks (they run indefinitely until stopped)
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(
                "multi_exchange_run_error",
                symbol=self.symbol,
                error=str(e),
                error_type=type(e).__name__,
            )

        finally:
            self.is_running = False
            logger.info("multi_exchange_manager_stopped", symbol=self.symbol)

    def stop(self) -> None:
        """
        Stop all exchange managers gracefully.

        This signals all exchange managers to stop and waits for
        clean disconnection.
        """
        logger.info("stopping_multi_exchange_manager", symbol=self.symbol)

        self._should_stop = True

        # Signal all exchange managers to stop
        for exchange_name, manager in self.exchanges.items():
            manager.stop()
            logger.info("exchange_stop_signal_sent", exchange=exchange_name, symbol=self.symbol)

        # Cancel all tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

    def get_orderbook(self, exchange: str) -> Optional[OrderBook]:
        """
        Get order book for a specific exchange.

        Args:
            exchange: Exchange name ("binance" or "bybit")

        Returns:
            OrderBook instance or None if exchange not enabled

        Example:
            >>> binance_book = manager.get_orderbook("binance")
            >>> best_bid = binance_book.get_best_bid()
        """
        manager = self.exchanges.get(exchange.lower())
        if manager:
            return manager.get_orderbook()
        return None

    def get_all_orderbooks(self) -> Dict[str, OrderBook]:
        """
        Get order books from all exchanges.

        Returns:
            Dictionary mapping exchange name to OrderBook instance

        Example:
            >>> books = manager.get_all_orderbooks()
            >>> for exchange, book in books.items():
            ...     print(f"{exchange}: {book.get_mid_price()}")
        """
        orderbooks = {}
        for exchange_name, manager in self.exchanges.items():
            orderbooks[exchange_name] = manager.get_orderbook()
        return orderbooks

    def get_status(self) -> Dict[str, Any]:
        """
        Get consolidated status from all exchanges.

        Returns:
            Dictionary with status information from each exchange

        Example:
            >>> status = manager.get_status()
            >>> print(status["binance"]["is_synchronized"])
            True
        """
        status: Dict[str, Any] = {
            "symbol": self.symbol,
            "is_running": self.is_running,
            "exchanges": {},
        }

        for exchange_name, manager in self.exchanges.items():
            status["exchanges"][exchange_name] = manager.get_status()

        return status

    def is_all_synchronized(self) -> bool:
        """
        Check if all exchanges are synchronized.

        Returns:
            True if all enabled exchanges are synchronized, False otherwise
        """
        return all(manager.is_synchronized for manager in self.exchanges.values())

    def get_spread_comparison(self) -> Optional[Dict[str, Any]]:
        """
        Compare bid-ask spreads across exchanges.

        This is a bonus feature that demonstrates cross-exchange analysis.

        Returns:
            Dictionary with spread comparison or None if data not available
        """
        if not self.is_all_synchronized():
            return None

        spreads = {}
        for exchange_name, manager in self.exchanges.items():
            orderbook = manager.get_orderbook()
            spread_bps = orderbook.get_spread_bps()
            if spread_bps is not None:
                spreads[exchange_name] = float(spread_bps)

        if len(spreads) < 2:
            return None

        return {
            "symbol": self.symbol,
            "spreads": spreads,
            "spread_difference_bps": max(spreads.values()) - min(spreads.values()),
            "tightest_exchange": min(spreads, key=spreads.get),  # type: ignore[arg-type]
            "widest_exchange": max(spreads, key=spreads.get),  # type: ignore[arg-type]
        }

    def get_arbitrage_opportunities(self) -> Optional[Dict[str, Any]]:
        """
        Detect potential arbitrage opportunities between exchanges.

        Compares best bid/ask across exchanges to identify price discrepancies.

        Returns:
            Dictionary with arbitrage information or None if not available
        """
        if not self.is_all_synchronized():
            return None

        orderbooks = self.get_all_orderbooks()

        # Get best prices from each exchange
        best_bids = {}
        best_asks = {}

        for exchange_name, orderbook in orderbooks.items():
            best_bid = orderbook.get_best_bid()
            best_ask = orderbook.get_best_ask()

            if best_bid:
                best_bids[exchange_name] = float(best_bid[0])
            if best_ask:
                best_asks[exchange_name] = float(best_ask[0])

        if len(best_bids) < 2 or len(best_asks) < 2:
            return None

        # Find arbitrage: Buy from exchange with lowest ask, sell to exchange with highest bid
        lowest_ask_exchange = min(best_asks, key=best_asks.get)  # type: ignore[arg-type]
        highest_bid_exchange = max(best_bids, key=best_bids.get)  # type: ignore[arg-type]

        lowest_ask = best_asks[lowest_ask_exchange]
        highest_bid = best_bids[highest_bid_exchange]

        # Arbitrage exists if we can buy cheaper than we can sell
        arbitrage_exists = highest_bid > lowest_ask

        if arbitrage_exists:
            spread = highest_bid - lowest_ask
            spread_bps = (spread / lowest_ask) * 10000

            return {
                "symbol": self.symbol,
                "arbitrage_exists": True,
                "buy_from": lowest_ask_exchange,
                "buy_price": lowest_ask,
                "sell_to": highest_bid_exchange,
                "sell_price": highest_bid,
                "spread_usd": spread,
                "spread_bps": spread_bps,
            }

        return {
            "symbol": self.symbol,
            "arbitrage_exists": False,
            "reason": "No profitable arbitrage opportunity",
        }

    def __repr__(self) -> str:
        """String representation of multi-exchange manager."""
        exchange_list = ", ".join(self.exchanges.keys())
        return f"MultiExchangeManager(symbol={self.symbol}, exchanges=[{exchange_list}])"
