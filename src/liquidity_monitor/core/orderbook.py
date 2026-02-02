"""
Order Book implementation using SortedDict for O(log n) operations.

This module provides a high-performance order book data structure optimized
for real-time market data processing in HFT systems.
"""

import zlib
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sortedcontainers import SortedDict

from ..utils.logger import get_logger

logger = get_logger(__name__)


class OrderBook:
    """
    Real-time Level-2 order book with O(log n) update complexity.

    Uses SortedDict to maintain price levels in sorted order, enabling:
    - O(log n) insertion/update/deletion
    - O(1) best bid/ask access
    - O(k) depth calculation for k levels

    Attributes:
        symbol: Trading pair symbol (e.g., "BTCUSDT")
        bids: SortedDict mapping price -> quantity (highest first)
        asks: SortedDict mapping price -> quantity (lowest first)
        last_update_id: Last processed update ID from exchange

    Example:
        >>> book = OrderBook("BTCUSDT")
        >>> book.update_bid(Decimal("50000.00"), Decimal("1.5"))
        >>> book.update_ask(Decimal("50010.00"), Decimal("2.0"))
        >>> best_bid_price, best_bid_qty = book.get_best_bid()
    """

    def __init__(self, symbol: str):
        """
        Initialize an empty order book.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
        """
        self.symbol = symbol
        self.bids: SortedDict[Decimal, Decimal] = SortedDict()
        self.asks: SortedDict[Decimal, Decimal] = SortedDict()
        self.last_update_id: int = 0
        self._first_update_after_snapshot: bool = True  # Track if we need special validation

        logger.info("orderbook_initialized", symbol=symbol)

    def update_bid(self, price: Decimal, quantity: Decimal) -> None:
        """
        Update a bid level. O(log n) complexity.

        Args:
            price: Bid price level
            quantity: New quantity (0 means remove the level)
        """
        if quantity == 0:
            self.bids.pop(price, None)
        else:
            self.bids[price] = quantity

    def update_ask(self, price: Decimal, quantity: Decimal) -> None:
        """
        Update an ask level. O(log n) complexity.

        Args:
            price: Ask price level
            quantity: New quantity (0 means remove the level)
        """
        if quantity == 0:
            self.asks.pop(price, None)
        else:
            self.asks[price] = quantity

    def get_best_bid(self) -> Optional[Tuple[Decimal, Decimal]]:
        """
        Get the best (highest) bid price and quantity. O(1) complexity.

        Returns:
            Tuple of (price, quantity) or None if no bids exist
        """
        if not self.bids:
            return None
        item: Tuple[Decimal, Decimal] = self.bids.peekitem(-1)  # Last item = highest price
        return item

    def get_best_ask(self) -> Optional[Tuple[Decimal, Decimal]]:
        """
        Get the best (lowest) ask price and quantity. O(1) complexity.

        Returns:
            Tuple of (price, quantity) or None if no asks exist
        """
        if not self.asks:
            return None
        item: Tuple[Decimal, Decimal] = self.asks.peekitem(0)  # First item = lowest price
        return item

    def get_mid_price(self) -> Optional[Decimal]:
        """
        Calculate mid-price between best bid and best ask.

        Returns:
            Mid-price or None if either side is empty
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()

        if best_bid is None or best_ask is None:
            return None

        # Ensure both prices are Decimal and divide by Decimal(2) to maintain type
        return (Decimal(str(best_bid[0])) + Decimal(str(best_ask[0]))) / Decimal("2")

    def is_crossed(self) -> bool:
        """
        Detect if order book is crossed (Bid >= Ask).

        A crossed order book indicates data corruption, usually caused by:
        - Missed delete orders (ghost orders)
        - Snapshot/Delta synchronization failures
        - Network packet loss

        Returns:
            True if order book is crossed (CORRUPTED), False otherwise

        Example:
            >>> if book.is_crossed():
            ...     logger.error("Crossed order book detected! Resyncing...")
            ...     await resync_orderbook()
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()

        if best_bid is None or best_ask is None:
            return False

        # Bid should ALWAYS be less than Ask
        # If Bid >= Ask, the order book is CROSSED (corrupted)
        return best_bid[0] >= best_ask[0]

    def get_spread_bps(self) -> Optional[Decimal]:
        """
        Calculate bid-ask spread in basis points.

        Returns:
            Spread in bps or None if cannot be calculated
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()

        if best_bid is None or best_ask is None:
            return None

        mid_price = self.get_mid_price()
        if mid_price is None or mid_price == 0:
            return None

        # Ensure Decimal types throughout calculation
        spread = Decimal(str(best_ask[0])) - Decimal(str(best_bid[0]))
        spread_bps = (spread / mid_price) * Decimal("10000")

        return spread_bps

    def apply_snapshot(
        self, bids: List[List[str]], asks: List[List[str]], last_update_id: int
    ) -> None:
        """
        Initialize order book from REST API snapshot.

        Args:
            bids: List of [price, quantity] pairs for bids
            asks: List of [price, quantity] pairs for asks
            last_update_id: The lastUpdateId from the snapshot

        Example:
            >>> book.apply_snapshot(
            ...     bids=[["50000.00", "1.5"], ["49990.00", "2.0"]],
            ...     asks=[["50010.00", "1.0"], ["50020.00", "2.5"]],
            ...     last_update_id=12345678
            ... )
        """
        # Clear existing data
        self.bids.clear()
        self.asks.clear()

        # Apply bid levels
        for price_str, qty_str in bids:
            price = Decimal(price_str)
            qty = Decimal(qty_str)
            if qty > 0:
                self.bids[price] = qty

        # Apply ask levels
        for price_str, qty_str in asks:
            price = Decimal(price_str)
            qty = Decimal(qty_str)
            if qty > 0:
                self.asks[price] = qty

        self.last_update_id = last_update_id
        self._first_update_after_snapshot = True  # Reset flag for next update

        logger.info(
            "snapshot_applied",
            symbol=self.symbol,
            bid_levels=len(self.bids),
            ask_levels=len(self.asks),
            last_update_id=last_update_id,
        )

    def apply_update(
        self,
        bids: List[List[str]],
        asks: List[List[str]],
        first_update_id: int,
        final_update_id: int,
    ) -> bool:
        """
        Apply incremental WebSocket update to order book.

        Handles Binance's update sequence validation for @depth@100ms:
        - U (first_update_id): First update ID in this event
        - u (final_update_id): Final update ID in this event
        - Sequence IDs are NOT consecutive in @depth@100ms (Binance skips intermediate updates)
        - We only validate that updates move FORWARD, not that every ID is present

        Args:
            bids: List of [price, quantity] updates for bids
            asks: List of [price, quantity] updates for asks
            first_update_id: First update ID in this event (U)
            final_update_id: Final update ID in this event (u)

        Returns:
            True if update was applied, False if it was dropped

        Raises:
            ValueError: If update sequence is backwards or invalid
        """
        # Validation logic for @depth@100ms stream:
        # 1. First processed event should have U <= lastUpdateId+1 AND u >= lastUpdateId+1
        # 2. Subsequent events should have U > lastUpdateId (LENIENT, allows gaps)

        if self._first_update_after_snapshot:
            # First update after snapshot must bridge the gap
            # The update should overlap with or immediately follow the snapshot
            if not (first_update_id <= self.last_update_id + 1 <= final_update_id):
                # ✅ Only log validation errors, not success
                logger.warning(
                    "invalid_first_update_after_snapshot",
                    symbol=self.symbol,
                    first_update_id=first_update_id,
                    final_update_id=final_update_id,
                    snapshot_last_update_id=self.last_update_id,
                    expected_range=f"U <= {self.last_update_id + 1} <= u",
                )
                return False
            # Mark that we've processed the first update (NO logging for performance)
            self._first_update_after_snapshot = False
        else:
            # ✅ FAST PATH: Subsequent updates (lenient for @depth@100ms)
            # For @depth@100ms stream, sequence IDs are NOT consecutive
            # Binance skips IDs because it only sends updates every 100ms
            # We only check that IDs are moving FORWARD, not that they're consecutive

            # Check if this is a duplicate or backwards (already processed)
            if final_update_id <= self.last_update_id:
                # Silently skip duplicates (common in HFT)
                return False

            # Check if update is too old (first_update_id should be >= last_update_id)
            if first_update_id < self.last_update_id:
                logger.warning(
                    "backwards_sequence_detected",
                    symbol=self.symbol,
                    last_update_id=self.last_update_id,
                    first_update_id=first_update_id,
                    final_update_id=final_update_id,
                )
                return False

            # ✅ LENIENT: Allow gaps for @depth@100ms (IDs are increasing, that's enough)
            # Gaps are EXPECTED in 100ms aggregated streams

        # Apply updates
        for price_str, qty_str in bids:
            self.update_bid(Decimal(price_str), Decimal(qty_str))

        for price_str, qty_str in asks:
            self.update_ask(Decimal(price_str), Decimal(qty_str))

        self.last_update_id = final_update_id

        return True

    def get_depth(self, levels: int = 10) -> Dict[str, List[Tuple[Decimal, Decimal]]]:
        """
        Get order book depth (top N levels).

        Args:
            levels: Number of levels to return per side

        Returns:
            Dictionary with 'bids' and 'asks' lists of (price, qty) tuples

        Example:
            >>> depth = book.get_depth(levels=5)
            >>> print(depth['bids'][:2])  # Top 2 bids
            [(Decimal('50000.00'), Decimal('1.5')), (Decimal('49990.00'), Decimal('2.0'))]
        """
        # Get top N bids (highest prices first)
        bid_items = list(self.bids.items())[-levels:] if levels > 0 else []
        bid_items.reverse()  # Highest to lowest

        # Get top N asks (lowest prices first)
        ask_items = list(self.asks.items())[:levels] if levels > 0 else []

        return {"bids": bid_items, "asks": ask_items}

    def get_stats(self) -> Dict[str, Any]:
        """
        Get order book statistics.

        Returns:
            Dictionary with current order book stats
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        mid_price = self.get_mid_price()
        spread_bps = self.get_spread_bps()

        return {
            "symbol": self.symbol,
            "bid_levels": len(self.bids),
            "ask_levels": len(self.asks),
            "best_bid": float(best_bid[0]) if best_bid else None,
            "best_ask": float(best_ask[0]) if best_ask else None,
            "mid_price": float(mid_price) if mid_price else None,
            "spread_bps": float(spread_bps) if spread_bps else None,
            "last_update_id": self.last_update_id,
        }

    def compute_checksum(self, depth: int = 10) -> int:
        """
        Compute CRC32 checksum of order book state.

        This implements the standard exchange checksum algorithm used by
        Binance, OKX, and other exchanges to verify order book integrity.

        The checksum is computed from the concatenation of:
        - Top N bid levels (price:quantity)
        - Top N ask levels (price:quantity)

        Args:
            depth: Number of levels to include in checksum (default 10)

        Returns:
            CRC32 checksum as unsigned 32-bit integer

        Example:
            >>> book.compute_checksum(depth=10)
            2849257112
        """
        # Build payload from top N levels
        payload_parts: List[str] = []

        # Get top N bids (highest to lowest)
        bid_items = list(self.bids.items())[-depth:] if depth > 0 else []
        bid_items.reverse()

        for price, qty in bid_items:
            # Format: "price:quantity" with minimal precision
            payload_parts.append(f"{price}:{qty}")

        # Get top N asks (lowest to highest)
        ask_items = list(self.asks.items())[:depth] if depth > 0 else []

        for price, qty in ask_items:
            payload_parts.append(f"{price}:{qty}")

        # Concatenate all parts
        payload = ":".join(payload_parts)

        # Compute CRC32 checksum
        checksum = zlib.crc32(payload.encode("utf-8")) & 0xFFFFFFFF

        return checksum

    def __repr__(self) -> str:
        """String representation of order book."""
        stats = self.get_stats()
        return (
            f"OrderBook(symbol={self.symbol}, "
            f"bids={stats['bid_levels']}, "
            f"asks={stats['ask_levels']}, "
            f"mid_price={stats['mid_price']})"
        )
