"""
Bybit Futures WebSocket connector for real-time order book data.

This module provides a production-grade WebSocket client for Bybit that:
- Maintains persistent connection to Bybit Futures
- Handles reconnections with exponential backoff
- Synchronizes local order book with exchange state
- Implements Update ID continuity checking for data integrity (Bybit V5 standard)
- Tracks connection latency and performance metrics
"""

import asyncio
import contextlib
import json
import ssl
import time
import types
from decimal import Decimal
from typing import Any, Dict, Optional, cast

import aiohttp
import certifi
import websockets
from websockets.asyncio.client import ClientConnection

# ⚡ Use orjson for BARE-METAL performance
json_parser: types.ModuleType
try:
    import orjson

    json_parser = orjson
    USE_ORJSON = True
except ImportError:
    json_parser = json
    USE_ORJSON = False

from ..core.orderbook import OrderBook  # noqa: E402
from ..utils.latency_monitor import LatencyMonitor  # noqa: E402
from ..utils.logger import PerformanceLogger, get_logger  # noqa: E402

logger = get_logger(__name__)


class BybitOrderBookManager:
    """
    Manages real-time order book synchronization with Bybit Futures.

    CRITICAL DIFFERENCES from Binance:

    1. **WebSocket Auto-Snapshot**: Bybit sends snapshot automatically when you subscribe!
       - Do NOT fetch REST API snapshot (different Update ID sequence)
       - Simply wait for first WebSocket snapshot message

    2. **Update ID Continuity**: Bybit V5 uses consecutive Update IDs (u) for integrity
       - NOT checksum-based like some exchanges
       - If u != last_u + 1, packet loss detected

    3. **Simpler Flow**:
       - Subscribe → Wait for snapshot → Process deltas
       - No buffering, no REST API needed!

    Attributes:
        symbol: Trading pair symbol (e.g., "BTCUSDT")
        orderbook: Local order book instance
        ws_url: WebSocket stream URL
        rest_url: REST API base URL

    Example:
        >>> manager = BybitOrderBookManager("BTCUSDT")
        >>> await manager.initialize()
        >>> await manager.run()
    """

    def __init__(
        self,
        symbol: str,
        ws_url: str = "wss://stream.bybit.com/v5/public/linear",
        rest_url: str = "https://api.bybit.com",
        reconnect_delay: float = 2.0,
        max_reconnect_delay: float = 60.0,
        ping_interval: float = 20.0,
        depth: int = 50,
    ):
        """
        Initialize Bybit Order Book Manager.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            ws_url: WebSocket base URL
            rest_url: REST API base URL
            reconnect_delay: Initial reconnection delay in seconds
            max_reconnect_delay: Maximum reconnection delay in seconds
            ping_interval: Ping interval to keep connection alive
            depth: Order book depth (1, 50, 200, 500)
        """
        self.symbol = symbol.upper()
        self.ws_url = ws_url
        self.rest_url = rest_url
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.ping_interval = ping_interval
        self.depth = depth

        # Order book
        self.orderbook = OrderBook(self.symbol)

        # WebSocket connection
        self.websocket: Optional[ClientConnection] = None
        self.is_connected: bool = False
        self.is_synchronized: bool = False

        # Performance metrics
        self.last_message_time: float = 0.0
        self.message_count: int = 0
        self.reconnect_count: int = 0

        # Checksum validation
        # Note: Bybit V5 WebSocket does NOT provide checksum field
        # We rely on Update ID (u) continuity checking instead
        self.enable_checksum_validation: bool = False  # Disabled for Bybit V5
        self.checksum_mismatch_count: int = 0
        self.checksum_success_count: int = 0

        # Update ID tracking for continuity checking
        self.last_processed_update_id: int = 0
        self.update_id_gap_count: int = 0

        # Crossed order book detection
        self.crossed_book_count: int = 0

        # Latency monitoring (Feature C: HFT-grade performance tracking)
        # Note: Bybit's 'ts' is matching engine time, so expect higher latency
        # than Binance's event time
        self.latency_monitor = LatencyMonitor(
            window_size=1000,
            warning_threshold_ms=100.0,  # Bybit: 100ms warning (vs Binance 50ms)
            critical_threshold_ms=200.0,  # Bybit: 200ms critical (vs Binance 100ms)
        )

        # Control flags
        self._should_stop: bool = False
        self._listener_task: Optional[asyncio.Task[None]] = None

        logger.info(
            "bybit_manager_initialized", symbol=self.symbol, ws_url=ws_url, rest_url=rest_url
        )

    async def fetch_snapshot(self) -> Dict[str, Any]:
        """
        Fetch order book snapshot via REST API.

        Returns:
            Snapshot data with Bybit structure

        Raises:
            aiohttp.ClientError: If REST request fails
        """
        url = f"{self.rest_url}/v5/market/orderbook"
        params = {"category": "linear", "symbol": self.symbol, "limit": self.depth}

        logger.info("fetching_snapshot", symbol=self.symbol, limit=self.depth)

        with PerformanceLogger(logger, "fetch_snapshot", symbol=self.symbol):
            ssl_context = ssl.create_default_context(cafile=certifi.where())

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, ssl=ssl_context) as response:
                    response.raise_for_status()
                    snapshot_bytes = await response.read()

                    loop = asyncio.get_running_loop()
                    if USE_ORJSON:
                        data = await loop.run_in_executor(None, orjson.loads, snapshot_bytes)
                    else:
                        data = await loop.run_in_executor(None, json.loads, snapshot_bytes)

        # Extract result
        result = data["result"]

        logger.info(
            "snapshot_fetched",
            symbol=self.symbol,
            bid_levels=len(result["b"]),
            ask_levels=len(result["a"]),
        )

        return cast(Dict[str, Any], result)

    def _verify_checksum(self, checksum_from_exchange: int) -> bool:
        """
        Verify order book checksum against exchange-provided value.

        **IMPORTANT: Bybit V5 does NOT provide checksum in WebSocket messages!**

        This method is kept for compatibility but is disabled by default for Bybit.
        Bybit V5 relies on Update ID (u) continuity checking instead.

        If you're using a different Bybit API version that provides checksums,
        you can enable this by setting self.enable_checksum_validation = True.

        Args:
            checksum_from_exchange: Checksum value from exchange (if provided)

        Returns:
            True if checksum matches or validation is disabled, False otherwise
        """
        if not self.enable_checksum_validation:
            return True

        try:
            local_checksum = self.orderbook.compute_checksum(depth=25)

            if local_checksum == checksum_from_exchange:
                self.checksum_success_count += 1
                return True
            else:
                self.checksum_mismatch_count += 1
                logger.error(
                    "checksum_mismatch_detected",
                    symbol=self.symbol,
                    exchange_checksum=checksum_from_exchange,
                    local_checksum=local_checksum,
                    message_count=self.message_count,
                )
                return False

        except Exception as e:
            logger.error("checksum_verification_error", symbol=self.symbol, error=str(e))
            return False

    async def _wait_for_websocket_snapshot(self) -> bool:
        """
        Wait for the first WebSocket snapshot from Bybit.

        CRITICAL: Bybit V5 WebSocket automatically sends a snapshot when you subscribe!
        Unlike Binance, we do NOT need to fetch snapshot via REST API.

        Bybit V5 standard flow:
        1. Subscribe to WebSocket
        2. Wait for first "snapshot" message (sent automatically)
        3. Process subsequent "delta" messages

        Why NOT use REST API?
        - REST API and WebSocket have DIFFERENT Update ID sequences
        - Mixing them causes 49M+ gaps
        - WebSocket snapshot is guaranteed to match subsequent deltas

        Returns:
            True if snapshot received, False if timeout
        """
        logger.info("waiting_for_websocket_snapshot", symbol=self.symbol)

        # Wait up to 10 seconds for first snapshot
        max_wait = 10.0
        start_time = time.time()

        # Track if we've seen the snapshot (use update_id as indicator)
        initial_update_id = self.last_processed_update_id

        while not self._should_stop:
            await asyncio.sleep(0.1)

            # Check if we received a snapshot (update_id changed from initial)
            if self.last_processed_update_id > initial_update_id:
                logger.info(
                    "websocket_snapshot_received",
                    symbol=self.symbol,
                    update_id=self.last_processed_update_id,
                )
                return True

            elapsed = time.time() - start_time
            if elapsed > max_wait:
                logger.error(
                    "snapshot_timeout",
                    symbol=self.symbol,
                    elapsed=elapsed,
                )
                return False

        return False

    async def _listen_and_process(self) -> None:
        """
        Listen to WebSocket and process order book updates.

        Bybit V5 WebSocket flow:
        1. First message is always a "snapshot" (sent automatically)
        2. Subsequent messages are "delta" updates
        3. Occasionally, Bybit may resend "snapshot" (e.g., no change in 3s for level 1)

        CRITICAL: We only use WebSocket snapshots, never REST API!
        REST API has different Update ID sequence and causes massive gaps.
        """
        if not self.websocket:
            logger.error("websocket_not_connected", symbol=self.symbol)
            return

        logger.info("started_listener_task", symbol=self.symbol)

        try:
            async for raw_message in self.websocket:
                if self._should_stop:
                    break

                if isinstance(raw_message, bytes):
                    continue

                try:
                    # ⚡ NON-BLOCKING: Fast JSON parsing
                    if USE_ORJSON:
                        message = orjson.loads(raw_message)
                    else:
                        message = json_parser.loads(raw_message)

                    # Handle orderbook messages
                    if "topic" in message:
                        await self._process_orderbook_message(message)

                    self.message_count += 1
                    self.last_message_time = time.time()

                    # Log stats every 1000 messages
                    if self.message_count % 1000 == 0:
                        stats = self.orderbook.get_stats()
                        latency_stats = self.latency_monitor.get_statistics()
                        logger.info(
                            "orderbook_stats",
                            symbol=self.symbol,
                            message_count=self.message_count,
                            update_id_gaps=self.update_id_gap_count,
                            crossed_books=self.crossed_book_count,
                            latency_p99_ms=latency_stats["p99_ms"],
                            **stats,
                        )

                except Exception as e:
                    logger.error(
                        "message_parse_error",
                        symbol=self.symbol,
                        error=str(e)[:100],
                        error_type=type(e).__name__,
                    )

        except asyncio.CancelledError:
            # Graceful shutdown - user stopped the program
            logger.info(
                "listener_task_cancelled",
                symbol=self.symbol,
                message_count=self.message_count,
            )
            self.is_connected = False

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("connection_closed", symbol=self.symbol, code=e.code, reason=e.reason)
            self.is_connected = False

        except Exception as e:
            logger.error(
                "listener_loop_error", symbol=self.symbol, error=str(e), error_type=type(e).__name__
            )
            self.is_connected = False

        finally:
            logger.info(
                "listener_task_exited",
                symbol=self.symbol,
                message_count=self.message_count,
                is_connected=self.is_connected,
            )

    async def _apply_delta_update(self, message: Dict[str, Any]) -> None:
        """
        Apply a single delta update to the order book.

        CRITICAL: This method must DISCARD any delta with Update ID <= last_processed_update_id.
        These are "ghost deltas" from before the snapshot and will corrupt the order book.

        Args:
            message: Delta message to apply
        """
        data = message.get("data", {})
        bids = data.get("b", [])
        asks = data.get("a", [])
        update_id = data.get("u", 0)

        # 🚨 CRITICAL: Discard stale deltas (Update ID <= Snapshot Update ID)
        # These deltas are from BEFORE the snapshot and will cause data corruption!
        if self.last_processed_update_id > 0 and update_id <= self.last_processed_update_id:
            logger.debug(
                "stale_delta_discarded",
                symbol=self.symbol,
                delta_update_id=update_id,
                last_processed=self.last_processed_update_id,
                action="discarded",
            )
            return  # ← DISCARD this delta!

        # ⚡ UPDATE ID CONTINUITY CHECK (Bybit's integrity mechanism)
        if self.last_processed_update_id > 0:
            expected_update_id = self.last_processed_update_id + 1
            if update_id != expected_update_id:
                gap_size = update_id - self.last_processed_update_id
                self.update_id_gap_count += 1

                # Only log significant gaps (> 5)
                if gap_size > 5:
                    logger.warning(
                        "update_id_gap_detected",
                        symbol=self.symbol,
                        expected=expected_update_id,
                        received=update_id,
                        gap_size=gap_size,
                        total_gaps=self.update_id_gap_count,
                    )

                # CRITICAL: If gap is massive (>1000), data may be corrupted
                # Reconnect and wait for new snapshot when gap exceeds threshold
                if gap_size > 1000:
                    logger.error(
                        "massive_update_id_gap",
                        symbol=self.symbol,
                        gap_size=gap_size,
                        action="reconnect_recommended",
                    )

        # Apply updates (MUST use Decimal for financial precision!)
        for price_str, qty_str in bids:
            self.orderbook.update_bid(price=Decimal(price_str), quantity=Decimal(qty_str))

        for price_str, qty_str in asks:
            self.orderbook.update_ask(price=Decimal(price_str), quantity=Decimal(qty_str))

        self.orderbook.last_update_id = update_id
        self.last_processed_update_id = update_id

        # 🚨 CROSSED ORDER BOOK DETECTION
        # Check if Bid >= Ask (data corruption - reconnect immediately)
        # Bybit's matching engine is ATOMIC - crossed book means data corruption!
        if self.orderbook.is_crossed():
            self.crossed_book_count += 1
            best_bid = self.orderbook.get_best_bid()
            best_ask = self.orderbook.get_best_ask()

            logger.error(
                "crossed_orderbook_detected",
                symbol=self.symbol,
                best_bid=float(best_bid[0]) if best_bid else None,
                best_ask=float(best_ask[0]) if best_ask else None,
                total_crossed=self.crossed_book_count,
                action="triggering_immediate_reconnect",
            )

            # CRITICAL: Mark as desynchronized to trigger immediate reconnect
            # Crossed book = stale delta pollution or real data corruption
            self.is_synchronized = False

    async def _process_orderbook_message(self, message: Dict[str, Any]) -> None:
        """
        Process order book message from Bybit.

        Message structure:
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot" or "delta",
            "ts": timestamp,
            "data": {
                "s": "BTCUSDT",
                "b": [["price", "qty"], ...],
                "a": [["price", "qty"], ...],
                "u": update_id,
                "seq": sequence_number
            }
        }

        Args:
            message: Order book update message from Bybit
        """
        try:
            # ⚡ LATENCY MONITORING (Feature C: HFT Performance Tracking)
            # Extract exchange event timestamp (ts field in milliseconds)
            if "ts" in message:
                exchange_timestamp_ms = float(message["ts"])
                self.latency_monitor.record_latency(exchange_timestamp_ms)

            msg_type = message.get("type")
            data = message.get("data", {})

            if msg_type == "snapshot":
                # Full snapshot - rebuild order book
                bids = data.get("b", [])
                asks = data.get("a", [])
                update_id = data.get("u", 0)

                self.orderbook.apply_snapshot(bids=bids, asks=asks, last_update_id=update_id)

                self.is_synchronized = True
                self.last_processed_update_id = update_id  # Reset Update ID tracker
                logger.info("bybit_snapshot_applied", symbol=self.symbol, update_id=update_id)

            elif msg_type == "delta":
                # Incremental update
                if not self.is_synchronized:
                    # Wait for synchronization first
                    return

                # Apply delta using dedicated method
                await self._apply_delta_update(message)

        except (KeyError, TypeError, ValueError) as e:
            logger.error("orderbook_update_failed", symbol=self.symbol, error=str(e))

    async def connect(self) -> None:
        """
        Establish WebSocket connection to Bybit.

        Raises:
            websockets.WebSocketException: If connection fails
        """
        logger.info("connecting_websocket", symbol=self.symbol, endpoint=self.ws_url)

        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())

            self.websocket = await websockets.connect(
                self.ws_url,
                ssl=ssl_context,
                ping_interval=self.ping_interval,
                ping_timeout=10,
                close_timeout=10,
                max_size=10 * 1024 * 1024,
            )

            # Subscribe to order book stream
            subscribe_message = {
                "op": "subscribe",
                "args": [f"orderbook.{self.depth}.{self.symbol}"],
            }

            await self.websocket.send(json.dumps(subscribe_message))

            self.is_connected = True
            self.last_message_time = time.time()

            logger.info(
                "websocket_connected", symbol=self.symbol, reconnect_count=self.reconnect_count
            )

        except Exception as e:
            logger.error(
                "connection_failed", symbol=self.symbol, error=str(e), error_type=type(e).__name__
            )
            raise

    async def disconnect(self) -> None:
        """Close WebSocket connection gracefully."""
        if self.websocket:
            await self.websocket.close()
            self.is_connected = False
            logger.info("websocket_disconnected", symbol=self.symbol)

    async def run(self) -> None:
        """
        Main run loop with automatic reconnection.

        This coroutine maintains the WebSocket connection indefinitely,
        automatically reconnecting on failures with exponential backoff.

        CRITICAL: Bybit V5 WebSocket automatically sends snapshot!
        - No need to fetch REST API snapshot
        - REST API and WebSocket have DIFFERENT Update ID sequences
        - Simply wait for first WebSocket snapshot, then process deltas
        """
        current_reconnect_delay = self.reconnect_delay

        logger.info("starting_bybit_manager", symbol=self.symbol)

        while not self._should_stop:
            try:
                # Connect to WebSocket
                await self.connect()

                # Start listener task
                self._listener_task = asyncio.create_task(self._listen_and_process())

                # ⚡ CRITICAL: Wait for first WebSocket snapshot (automatic)
                # Bybit will send it automatically when you subscribe!
                sync_success = await self._wait_for_websocket_snapshot()
                if not sync_success:
                    logger.error("websocket_snapshot_timeout", symbol=self.symbol)
                    raise Exception("Did not receive WebSocket snapshot")

                logger.info("bybit_sync_complete", symbol=self.symbol)

                # Reset reconnect delay on successful connection
                current_reconnect_delay = self.reconnect_delay

                # 🔄 Monitor loop: Check for corruption and resync if needed
                resync_needed = False
                while not self._should_stop:
                    await asyncio.sleep(0.5)  # Check twice per second

                    # Check if crossed order book triggered desync
                    if not self.is_synchronized:
                        resync_needed = True
                        logger.warning(
                            "corruption_detected_reconnecting",
                            symbol=self.symbol,
                            reason="crossed_orderbook_or_large_gap",
                            crossed_count=self.crossed_book_count,
                        )
                        break

                    # Check if listener task died unexpectedly
                    if self._listener_task.done():
                        # Check if task was cancelled vs completed with error
                        if self._listener_task.cancelled():
                            # Task was cancelled (normal shutdown path)
                            logger.debug("listener_task_was_cancelled", symbol=self.symbol)
                        else:
                            # Task completed - check if with exception
                            try:
                                self._listener_task.result()  # Will raise if there was exception
                                # No exception - completed normally (shouldn't happen for long-running task)
                                logger.warning(
                                    "listener_task_completed_normally", symbol=self.symbol
                                )
                            except Exception as exc:
                                # Task died with exception - this is a real error
                                logger.error(
                                    "listener_task_died_with_exception",
                                    symbol=self.symbol,
                                    error=str(exc)[:100],
                                    error_type=type(exc).__name__,
                                )
                        break

                # If resync needed, force reconnection for fresh snapshot
                if resync_needed:
                    # CRITICAL: Clear corrupted order book before reconnecting
                    # Otherwise new data will be applied to corrupted state
                    logger.info(
                        "clearing_corrupted_orderbook",
                        symbol=self.symbol,
                        reason="preparing_for_reconnect",
                    )
                    self.orderbook.bids.clear()
                    self.orderbook.asks.clear()
                    self.is_synchronized = False  # Reset sync flag
                    self.last_processed_update_id = 0  # Reset update ID tracker

                    logger.info(
                        "forcing_reconnection",
                        symbol=self.symbol,
                        reason="get_fresh_snapshot",
                    )

            except asyncio.CancelledError:
                # Graceful shutdown - user stopped the program
                logger.info("bybit_manager_stopped", symbol=self.symbol)

                # Cancel listener task if still running
                if self._listener_task and not self._listener_task.done():
                    self._listener_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._listener_task
                break  # Exit the reconnection loop

            except Exception as e:
                logger.error(
                    "run_error", symbol=self.symbol, error=str(e), error_type=type(e).__name__
                )

                # Cancel listener task if still running
                if self._listener_task and not self._listener_task.done():
                    self._listener_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._listener_task

                self.reconnect_count += 1

                # Exponential backoff
                logger.info(
                    "reconnecting",
                    symbol=self.symbol,
                    delay=current_reconnect_delay,
                    attempt=self.reconnect_count,
                )

                await asyncio.sleep(current_reconnect_delay)
                current_reconnect_delay = min(current_reconnect_delay * 2, self.max_reconnect_delay)

            finally:
                if self._listener_task and not self._listener_task.done():
                    self._listener_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._listener_task
                    self._listener_task = None

                await self.disconnect()

        # Note: "bybit_manager_stopped" already logged in CancelledError handler
        # Only log if stopped for other reasons
        if not self._should_stop:
            logger.info("bybit_manager_exited", symbol=self.symbol)

    def stop(self) -> None:
        """Signal the manager to stop gracefully."""
        logger.info("stopping_bybit_manager", symbol=self.symbol)
        self._should_stop = True

    def get_orderbook(self) -> OrderBook:
        """
        Get the current order book instance.

        Returns:
            OrderBook instance
        """
        return self.orderbook

    def get_status(self) -> Dict[str, Any]:
        """
        Get current connection and performance status.

        Returns:
            Dictionary with status information
        """
        time_since_last_msg = (
            time.time() - self.last_message_time if self.last_message_time > 0 else None
        )

        return {
            "symbol": self.symbol,
            "exchange": "bybit",
            "is_connected": self.is_connected,
            "is_synchronized": self.is_synchronized,
            "message_count": self.message_count,
            "reconnect_count": self.reconnect_count,
            "update_id_gap_count": self.update_id_gap_count,  # Bybit V5: Update ID continuity
            "crossed_book_count": self.crossed_book_count,  # Data corruption detection
            "checksum_validation_enabled": self.enable_checksum_validation,  # False for Bybit V5
            "time_since_last_message_ms": (
                round(time_since_last_msg * 1000, 2) if time_since_last_msg else None
            ),
            "orderbook_stats": self.orderbook.get_stats(),
            "latency_stats": self.latency_monitor.get_statistics(),
        }
