"""
Unit tests for OrderBook implementation.

Tests cover:
- Order book initialization
- Bid/ask updates
- Best bid/ask retrieval
- Price level ordering
- Snapshot application
- Incremental updates
- Edge cases (empty book, zero quantities)
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from liquidity_monitor.core.orderbook import OrderBook  # noqa: E402


class TestOrderBookBasics:
    """Test basic order book operations."""

    def test_initialization(self):
        """Test order book initializes empty."""
        book = OrderBook("BTCUSDT")

        assert book.symbol == "BTCUSDT"
        assert len(book.bids) == 0
        assert len(book.asks) == 0
        assert book.last_update_id == 0
        assert book.get_best_bid() is None
        assert book.get_best_ask() is None

    def test_update_bid_single_level(self):
        """Test adding a single bid level."""
        book = OrderBook("BTCUSDT")

        book.update_bid(Decimal("50000.00"), Decimal("1.5"))

        assert len(book.bids) == 1
        assert book.bids[Decimal("50000.00")] == Decimal("1.5")

    def test_update_ask_single_level(self):
        """Test adding a single ask level."""
        book = OrderBook("BTCUSDT")

        book.update_ask(Decimal("50010.00"), Decimal("2.0"))

        assert len(book.asks) == 1
        assert book.asks[Decimal("50010.00")] == Decimal("2.0")

    def test_update_bid_zero_quantity_removes(self):
        """Test that zero quantity removes bid level."""
        book = OrderBook("BTCUSDT")

        book.update_bid(Decimal("50000.00"), Decimal("1.5"))
        assert len(book.bids) == 1

        book.update_bid(Decimal("50000.00"), Decimal("0"))
        assert len(book.bids) == 0

    def test_update_ask_zero_quantity_removes(self):
        """Test that zero quantity removes ask level."""
        book = OrderBook("BTCUSDT")

        book.update_ask(Decimal("50010.00"), Decimal("2.0"))
        assert len(book.asks) == 1

        book.update_ask(Decimal("50010.00"), Decimal("0"))
        assert len(book.asks) == 0


class TestOrderBookOrdering:
    """Test that order book maintains correct price ordering."""

    def test_bids_sorted_descending(self):
        """Test bids are sorted highest to lowest."""
        book = OrderBook("BTCUSDT")

        # Add bids in random order
        book.update_bid(Decimal("50000.00"), Decimal("1.0"))
        book.update_bid(Decimal("49990.00"), Decimal("2.0"))
        book.update_bid(Decimal("50005.00"), Decimal("1.5"))

        # Get all bids (should be sorted highest to lowest)
        bid_prices = list(book.bids.keys())

        assert bid_prices == [Decimal("49990.00"), Decimal("50000.00"), Decimal("50005.00")]

    def test_asks_sorted_ascending(self):
        """Test asks are sorted lowest to highest."""
        book = OrderBook("BTCUSDT")

        # Add asks in random order
        book.update_ask(Decimal("50020.00"), Decimal("1.0"))
        book.update_ask(Decimal("50010.00"), Decimal("2.0"))
        book.update_ask(Decimal("50015.00"), Decimal("1.5"))

        # Get all asks (should be sorted lowest to highest)
        ask_prices = list(book.asks.keys())

        assert ask_prices == [Decimal("50010.00"), Decimal("50015.00"), Decimal("50020.00")]

    def test_best_bid_is_highest(self):
        """Test get_best_bid returns highest bid price."""
        book = OrderBook("BTCUSDT")

        book.update_bid(Decimal("50000.00"), Decimal("1.0"))
        book.update_bid(Decimal("49990.00"), Decimal("2.0"))
        book.update_bid(Decimal("50005.00"), Decimal("1.5"))

        best_bid = book.get_best_bid()

        assert best_bid is not None
        assert best_bid[0] == Decimal("50005.00")
        assert best_bid[1] == Decimal("1.5")

    def test_best_ask_is_lowest(self):
        """Test get_best_ask returns lowest ask price."""
        book = OrderBook("BTCUSDT")

        book.update_ask(Decimal("50020.00"), Decimal("1.0"))
        book.update_ask(Decimal("50010.00"), Decimal("2.0"))
        book.update_ask(Decimal("50015.00"), Decimal("1.5"))

        best_ask = book.get_best_ask()

        assert best_ask is not None
        assert best_ask[0] == Decimal("50010.00")
        assert best_ask[1] == Decimal("2.0")


class TestOrderBookMetrics:
    """Test order book metric calculations."""

    def test_mid_price_calculation(self):
        """Test mid-price calculation."""
        book = OrderBook("BTCUSDT")

        book.update_bid(Decimal("50000.00"), Decimal("1.0"))
        book.update_ask(Decimal("50010.00"), Decimal("1.0"))

        mid_price = book.get_mid_price()

        assert mid_price == Decimal("50005.00")

    def test_mid_price_empty_book(self):
        """Test mid-price returns None for empty book."""
        book = OrderBook("BTCUSDT")

        assert book.get_mid_price() is None

    def test_mid_price_only_bids(self):
        """Test mid-price returns None when only bids exist."""
        book = OrderBook("BTCUSDT")

        book.update_bid(Decimal("50000.00"), Decimal("1.0"))

        assert book.get_mid_price() is None

    def test_mid_price_only_asks(self):
        """Test mid-price returns None when only asks exist."""
        book = OrderBook("BTCUSDT")

        book.update_ask(Decimal("50010.00"), Decimal("1.0"))

        assert book.get_mid_price() is None

    def test_spread_bps_calculation(self):
        """Test spread calculation in basis points."""
        book = OrderBook("BTCUSDT")

        book.update_bid(Decimal("50000.00"), Decimal("1.0"))
        book.update_ask(Decimal("50010.00"), Decimal("1.0"))

        spread_bps = book.get_spread_bps()

        # Spread = (50010 - 50000) / 50005 * 10000 = 1.999 bps
        assert spread_bps is not None
        assert abs(float(spread_bps) - 1.999) < 0.01

    def test_spread_bps_empty_book(self):
        """Test spread returns None for empty book."""
        book = OrderBook("BTCUSDT")

        assert book.get_spread_bps() is None


class TestOrderBookSnapshot:
    """Test snapshot application."""

    def test_apply_snapshot_basic(self):
        """Test applying a basic snapshot."""
        book = OrderBook("BTCUSDT")

        bids = [["50000.00", "1.5"], ["49990.00", "2.0"], ["49980.00", "1.0"]]
        asks = [["50010.00", "1.0"], ["50020.00", "2.5"], ["50030.00", "1.5"]]

        book.apply_snapshot(bids, asks, 12345678)

        assert len(book.bids) == 3
        assert len(book.asks) == 3
        assert book.last_update_id == 12345678

        # Check best bid/ask
        best_bid = book.get_best_bid()
        best_ask = book.get_best_ask()

        assert best_bid[0] == Decimal("50000.00")
        assert best_ask[0] == Decimal("50010.00")

    def test_apply_snapshot_clears_existing(self):
        """Test that snapshot clears existing data."""
        book = OrderBook("BTCUSDT")

        # Add some initial data
        book.update_bid(Decimal("40000.00"), Decimal("10.0"))
        book.update_ask(Decimal("60000.00"), Decimal("10.0"))

        assert len(book.bids) == 1
        assert len(book.asks) == 1

        # Apply snapshot
        bids = [["50000.00", "1.5"]]
        asks = [["50010.00", "1.0"]]

        book.apply_snapshot(bids, asks, 99999)

        assert len(book.bids) == 1
        assert len(book.asks) == 1
        assert book.bids[Decimal("50000.00")] == Decimal("1.5")
        assert Decimal("40000.00") not in book.bids

    def test_apply_snapshot_filters_zero_quantity(self):
        """Test that zero quantities are filtered out."""
        book = OrderBook("BTCUSDT")

        bids = [["50000.00", "1.5"], ["49990.00", "0.0"], ["49980.00", "1.0"]]  # Should be filtered
        asks = [["50010.00", "0.0"], ["50020.00", "2.5"]]  # Should be filtered

        book.apply_snapshot(bids, asks, 12345678)

        assert len(book.bids) == 2
        assert len(book.asks) == 1


class TestOrderBookUpdate:
    """Test incremental updates."""

    def test_apply_update_basic(self):
        """Test applying a basic update."""
        book = OrderBook("BTCUSDT")

        # Apply snapshot first
        bids = [["50000.00", "1.5"]]
        asks = [["50010.00", "1.0"]]
        book.apply_snapshot(bids, asks, 100)

        # Apply update
        update_bids = [["50005.00", "2.0"]]
        update_asks = [["50015.00", "1.5"]]

        result = book.apply_update(update_bids, update_asks, 101, 101)

        assert result is True
        assert len(book.bids) == 2
        assert len(book.asks) == 2
        assert book.last_update_id == 101

    def test_apply_update_removes_level(self):
        """Test update can remove price level."""
        book = OrderBook("BTCUSDT")

        # Apply snapshot
        bids = [["50000.00", "1.5"], ["49990.00", "2.0"]]
        asks = [["50010.00", "1.0"]]
        book.apply_snapshot(bids, asks, 100)

        # Update to remove a level
        update_bids = [["50000.00", "0.0"]]

        result = book.apply_update(update_bids, [], 101, 101)

        assert result is True
        assert len(book.bids) == 1
        assert Decimal("50000.00") not in book.bids

    def test_apply_update_rejects_old_sequence(self):
        """Test that old updates are rejected."""
        book = OrderBook("BTCUSDT")

        # Apply snapshot
        bids = [["50000.00", "1.5"]]
        asks = [["50010.00", "1.0"]]
        book.apply_snapshot(bids, asks, 100)

        # Try to apply update with old sequence
        result = book.apply_update([], [], 50, 99)

        assert result is False
        assert book.last_update_id == 100

    def test_apply_update_allows_gaps_in_sequence(self):
        """Test that gaps in sequence are allowed (for @depth@100ms)."""
        book = OrderBook("BTCUSDT")

        # Apply snapshot
        bids = [["50000.00", "1.5"]]
        asks = [["50010.00", "1.0"]]
        book.apply_snapshot(bids, asks, 100)

        # Apply update with gap that bridges the snapshot
        # For @depth@100ms, first update must have: U <= lastUpdateId+1 <= u
        result = book.apply_update([["50005.00", "1.0"]], [], 100, 110)

        assert result is True
        assert book.last_update_id == 110


class TestOrderBookDepth:
    """Test depth retrieval."""

    def test_get_depth_basic(self):
        """Test getting order book depth."""
        book = OrderBook("BTCUSDT")

        # Add multiple levels
        for i in range(10):
            book.update_bid(Decimal(f"{50000 - i * 10}.00"), Decimal("1.0"))
            book.update_ask(Decimal(f"{50010 + i * 10}.00"), Decimal("1.0"))

        depth = book.get_depth(levels=5)

        assert len(depth["bids"]) == 5
        assert len(depth["asks"]) == 5

        # Check that bids are highest to lowest
        assert depth["bids"][0][0] == Decimal("50000.00")
        assert depth["bids"][4][0] == Decimal("49960.00")

        # Check that asks are lowest to highest
        assert depth["asks"][0][0] == Decimal("50010.00")
        assert depth["asks"][4][0] == Decimal("50050.00")

    def test_get_depth_empty_book(self):
        """Test getting depth from empty book."""
        book = OrderBook("BTCUSDT")

        depth = book.get_depth(levels=10)

        assert len(depth["bids"]) == 0
        assert len(depth["asks"]) == 0


class TestOrderBookEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_book_returns_none_for_metrics(self):
        """Test that empty book returns None for all metrics."""
        book = OrderBook("BTCUSDT")

        assert book.get_best_bid() is None
        assert book.get_best_ask() is None
        assert book.get_mid_price() is None
        assert book.get_spread_bps() is None

    def test_large_price_precision(self):
        """Test handling of high precision prices."""
        book = OrderBook("BTCUSDT")

        book.update_bid(Decimal("50000.12345678"), Decimal("1.23456789"))
        book.update_ask(Decimal("50010.87654321"), Decimal("2.34567890"))

        best_bid = book.get_best_bid()
        best_ask = book.get_best_ask()

        assert best_bid[0] == Decimal("50000.12345678")
        assert best_bid[1] == Decimal("1.23456789")
        assert best_ask[0] == Decimal("50010.87654321")
        assert best_ask[1] == Decimal("2.34567890")

    def test_update_replaces_existing_level(self):
        """Test that updating existing level replaces quantity."""
        book = OrderBook("BTCUSDT")

        book.update_bid(Decimal("50000.00"), Decimal("1.0"))
        assert book.bids[Decimal("50000.00")] == Decimal("1.0")

        book.update_bid(Decimal("50000.00"), Decimal("5.0"))
        assert book.bids[Decimal("50000.00")] == Decimal("5.0")
        assert len(book.bids) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
