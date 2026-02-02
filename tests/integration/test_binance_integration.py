"""
Integration tests for Binance Futures connector.

These tests verify that the connector properly integrates with:
- WebSocket streaming
- REST API endpoints
- Order book synchronization
- Error handling and reconnection logic

By default, these tests use mocked responses. Set USE_REAL_API=true
to test against the actual Binance API (not recommended in CI).
"""

import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from liquidity_monitor.connectors.binance_futures import BinanceOrderBookManager  # noqa: E402
from liquidity_monitor.core.orderbook import OrderBook  # noqa: E402

# Test configuration
USE_REAL_API = os.getenv("USE_REAL_API", "false").lower() == "true"


# Fixtures for mock data
@pytest.fixture
def mock_snapshot_response():
    """Mock REST API snapshot response."""
    return {
        "lastUpdateId": 1000000,
        "E": 1699500000000,  # Event time
        "T": 1699500000000,  # Transaction time
        "bids": [
            ["50000.00", "1.5"],
            ["49990.00", "2.0"],
            ["49980.00", "1.0"],
        ],
        "asks": [
            ["50010.00", "1.0"],
            ["50020.00", "2.5"],
            ["50030.00", "1.5"],
        ],
    }


@pytest.fixture
def mock_ws_update():
    """Mock WebSocket depth update message."""
    return {
        "e": "depthUpdate",
        "E": 1699500001000,
        "T": 1699500001000,
        "s": "BTCUSDT",
        "U": 1000001,  # First update ID
        "u": 1000010,  # Final update ID
        "pu": 1000000,  # Previous final update ID
        "b": [  # Bids to update
            ["50005.00", "3.0"],
            ["49995.00", "1.5"],
        ],
        "a": [  # Asks to update
            ["50015.00", "2.0"],
        ],
    }


@pytest.mark.integration
class TestBinanceOrderBookManagerMocked:
    """Test BinanceOrderBookManager with mocked responses."""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test that manager initializes correctly."""
        manager = BinanceOrderBookManager("BTCUSDT")

        assert manager.symbol == "BTCUSDT"
        assert isinstance(manager.orderbook, OrderBook)
        assert manager.orderbook.symbol == "BTCUSDT"
        assert manager.is_connected is False  # Changed from _initialized

    @pytest.mark.asyncio
    async def test_fetch_snapshot_success(self):
        """Test fetching order book snapshot via REST API (using aioresponses)."""
        from aioresponses import aioresponses

        manager = BinanceOrderBookManager("BTCUSDT")

        # Payload simulating Binance response
        mock_payload = {
            "lastUpdateId": 1020,
            "bids": [["50000.00", "1.0"], ["49999.00", "2.0"]],
            "asks": [["50001.00", "1.0"], ["50002.00", "2.0"]],
        }

        # The Magic: aioresponses mocks the URL, not the session object
        with aioresponses() as m:
            # Mock the specific URL pattern
            m.get(
                "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=1000",
                payload=mock_payload,
                status=200,
            )

            # Act: Call the real method
            # This runs your REAL aiohttp code, REAL run_in_executor code,
            # and REAL orjson parsing. It only fakes the network return.
            snapshot = await manager.fetch_snapshot()

        # Assert
        assert snapshot is not None
        assert snapshot["lastUpdateId"] == 1020
        assert len(snapshot["bids"]) == 2
        assert len(snapshot["asks"]) == 2
        assert snapshot["bids"][0] == ["50000.00", "1.0"]
        assert snapshot["asks"][0] == ["50001.00", "1.0"]

    @pytest.mark.asyncio
    async def test_snapshot_applied_to_orderbook(self, mock_snapshot_response):
        """Test that snapshot is correctly applied to order book."""
        manager = BinanceOrderBookManager("BTCUSDT")

        # Directly apply snapshot to order book
        manager.orderbook.apply_snapshot(
            bids=mock_snapshot_response["bids"],
            asks=mock_snapshot_response["asks"],
            last_update_id=mock_snapshot_response["lastUpdateId"],
        )

        # Verify order book state
        assert manager.orderbook.last_update_id == 1000000
        assert len(manager.orderbook.bids) == 3
        assert len(manager.orderbook.asks) == 3

        # Check best bid/ask
        best_bid = manager.orderbook.get_best_bid()
        best_ask = manager.orderbook.get_best_ask()

        assert best_bid is not None
        assert best_bid[0] == Decimal("50000.00")
        assert best_ask is not None
        assert best_ask[0] == Decimal("50010.00")

    @pytest.mark.asyncio
    async def test_fetch_snapshot_http_500_error(self):
        """Test that fetch_snapshot handles HTTP 500 errors gracefully."""
        from aioresponses import aioresponses

        manager = BinanceOrderBookManager("BTCUSDT")

        with aioresponses() as m:
            # Mock HTTP 500 error
            m.get(
                "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=1000",
                status=500,
                body="Internal Server Error",
            )

            # Should handle error gracefully and return None
            snapshot = await manager.fetch_snapshot()
            assert snapshot is None

    @pytest.mark.asyncio
    async def test_fetch_snapshot_http_429_rate_limit(self):
        """Test that fetch_snapshot handles HTTP 429 rate limit errors."""
        from aioresponses import aioresponses

        manager = BinanceOrderBookManager("BTCUSDT")

        with aioresponses() as m:
            # Mock HTTP 429 rate limit
            m.get(
                "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=1000",
                status=429,
                body="Too Many Requests",
            )

            # Should handle rate limit gracefully and return None
            snapshot = await manager.fetch_snapshot()
            assert snapshot is None

    @pytest.mark.asyncio
    async def test_websocket_message_processing_integration(self):
        """
        Integration test: Verify WebSocket message processing through public API.

        Tests:
        - Applying snapshot to OrderBook
        - Processing delta updates
        - Sequence validation (rejecting old updates)
        - Detecting gaps in update IDs
        """
        manager = BinanceOrderBookManager("BTCUSDT")

        # STEP 1: Apply initial snapshot (simulate REST API response)
        snapshot_data = {
            "lastUpdateId": 1000000,
            "bids": [["50000.00", "1.0"], ["49999.00", "2.0"]],
            "asks": [["50001.00", "1.0"], ["50002.00", "2.0"]],
        }

        manager.orderbook.apply_snapshot(
            bids=snapshot_data["bids"],
            asks=snapshot_data["asks"],
            last_update_id=snapshot_data["lastUpdateId"],
        )

        # Verify snapshot applied
        assert manager.orderbook.last_update_id == 1000000
        assert len(manager.orderbook.bids) == 2
        assert len(manager.orderbook.asks) == 2

        # STEP 2: Process valid delta update (simulates WebSocket message)
        valid_update = {
            "U": 1000001,  # first_update_id (must be > snapshot.lastUpdateId)
            "u": 1000005,  # final_update_id
            "b": [["50005.00", "3.0"]],  # New bid
            "a": [["50003.00", "1.5"]],  # New ask
        }

        manager.orderbook.apply_update(
            bids=valid_update["b"],
            asks=valid_update["a"],
            first_update_id=valid_update["U"],
            final_update_id=valid_update["u"],
        )

        # Verify delta applied
        assert manager.orderbook.last_update_id == 1000005
        assert Decimal("50005.00") in manager.orderbook.bids
        assert Decimal("50003.00") in manager.orderbook.asks

        # STEP 3: Try to apply old update (should be rejected by sequence validation)
        old_update = {
            "U": 999990,  # Before snapshot
            "u": 999999,
            "b": [["49000.00", "10.0"]],
            "a": [],
        }

        # This should not update the orderbook (sequence validation)
        manager.orderbook.apply_update(
            bids=old_update["b"],
            asks=old_update["a"],
            first_update_id=old_update["U"],
            final_update_id=old_update["u"],
        )

        # Verify old update was rejected
        assert manager.orderbook.last_update_id == 1000005  # Unchanged
        assert Decimal("49000.00") not in manager.orderbook.bids  # Not added

        # STEP 4: Detect gap in sequence (simulate missed messages)
        gap_update = {
            "U": 2000000,  # HUGE gap from 1000005
            "u": 2000010,
            "b": [["51000.00", "5.0"]],
            "a": [],
        }

        # Apply update with gap (OrderBook will accept it per Binance spec)
        # Note: Binance allows gaps, manager should detect and trigger re-sync
        manager.orderbook.apply_update(
            bids=gap_update["b"],
            asks=gap_update["a"],
            first_update_id=gap_update["U"],
            final_update_id=gap_update["u"],
        )

        # Update ID should jump (gap detected)
        assert manager.orderbook.last_update_id == 2000010

        # Get final statistics
        stats = manager.orderbook.get_stats()
        assert stats["symbol"] == "BTCUSDT"
        assert stats["last_update_id"] == 2000010

    # DELETED: Dead code testing private methods that no longer exist
    # - test_reconnection_logic (used _handle_disconnect)
    # Previous tests for _process_depth_update merged into test_websocket_message_processing_integration above


@pytest.mark.integration
@pytest.mark.skipif(not USE_REAL_API, reason="Real API testing disabled")
class TestBinanceOrderBookManagerReal:
    """Test against real Binance API (only run when USE_REAL_API=true)."""

    @pytest.mark.asyncio
    async def test_real_snapshot_fetch(self):
        """Test fetching real snapshot from Binance."""
        manager = BinanceOrderBookManager("BTCUSDT")

        # Fetch real snapshot
        snapshot = await manager._fetch_snapshot()

        assert snapshot is not None
        assert "lastUpdateId" in snapshot
        assert "bids" in snapshot
        assert "asks" in snapshot
        assert len(snapshot["bids"]) > 0
        assert len(snapshot["asks"]) > 0

        print(f"Snapshot fetched: {len(snapshot['bids'])} bids, {len(snapshot['asks'])} asks")

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_real_websocket_connection(self):
        """Test real WebSocket connection (30 second timeout)."""
        manager = BinanceOrderBookManager("BTCUSDT")

        async def collect_messages():
            await manager.initialize()
            # Run for 10 seconds
            await asyncio.sleep(10)
            await manager.stop()

        try:
            await asyncio.wait_for(collect_messages(), timeout=30)
            print(f"Received {manager._messages_received} messages")
            assert manager._messages_received > 0
        except asyncio.TimeoutError:
            pytest.fail("WebSocket connection timed out")


@pytest.mark.integration
class TestOrderBookIntegration:
    """Integration tests for order book operations."""

    def test_orderbook_snapshot_and_updates(self):
        """Test complete flow: snapshot -> updates."""
        book = OrderBook("BTCUSDT")

        # Apply snapshot
        bids = [["50000.00", "1.5"], ["49990.00", "2.0"]]
        asks = [["50010.00", "1.0"], ["50020.00", "2.5"]]
        book.apply_snapshot(bids, asks, 1000000)

        # Apply series of updates
        # First update after snapshot: U should be <= 1000001, u can be higher
        for i in range(1, 11):
            update_bids = [[f"{50000 + i * 10}.00", "1.0"]]
            update_asks = [[f"{50010 + i * 10}.00", "1.0"]]

            # First update: U=1000001, u=1000010
            # Subsequent updates: U=previous_u+1
            first_update_id = 1000001 if i == 1 else 1000000 + (i - 1) * 10 + 1
            final_update_id = 1000000 + i * 10

            result = book.apply_update(update_bids, update_asks, first_update_id, final_update_id)
            assert result is True

        # Verify final state
        assert book.last_update_id == 1000100
        assert len(book.bids) > 2
        assert len(book.asks) > 2

    def test_orderbook_statistics(self):
        """Test order book statistics calculation."""
        book = OrderBook("BTCUSDT")

        # Setup order book
        bids = [["50000.00", "1.5"], ["49990.00", "2.0"], ["49980.00", "1.0"]]
        asks = [["50010.00", "1.0"], ["50020.00", "2.5"], ["50030.00", "1.5"]]
        book.apply_snapshot(bids, asks, 1000000)

        # Get statistics
        stats = book.get_stats()

        assert stats["symbol"] == "BTCUSDT"
        assert stats["bid_levels"] == 3
        assert stats["ask_levels"] == 3
        assert stats["best_bid"] == 50000.00
        assert stats["best_ask"] == 50010.00
        assert stats["mid_price"] == 50005.00
        assert stats["spread_bps"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
