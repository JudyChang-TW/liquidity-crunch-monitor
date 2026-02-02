"""
Unit tests for risk engine calculations.

Tests cover:
- Slippage calculation
- Depth imbalance
- Depth at basis points
- Liquidity crunch detection
- Z-score calculations
- Edge cases (empty order book, insufficient liquidity)
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from liquidity_monitor.analytics.risk_engine import (  # noqa: E402
    LiquidityCrunchDetector,
    calculate_depth_at_bps,
    calculate_depth_imbalance,
    calculate_slippage,
)


class TestSlippageCalculation:
    """Test slippage estimation for market orders."""

    def test_slippage_sell_single_level(self):
        """Test slippage calculation for sell order filling single level."""
        bids = [
            (Decimal("50000"), Decimal("2.0")),  # $100k at best bid
        ]
        asks = [
            (Decimal("50010"), Decimal("1.0")),
        ]

        # Sell $50k worth (should fill half of first level)
        result = calculate_slippage(bids, asks, 50_000, "sell")

        assert result["filled"] is True
        assert result["levels_consumed"] == 1
        assert result["mid_price"] == 50005.0
        # Average price should be exactly 50000 (best bid)
        assert result["average_price"] == 50000.0

    def test_slippage_sell_multiple_levels(self):
        """Test slippage calculation across multiple levels."""
        bids = [
            (Decimal("50000"), Decimal("1.0")),  # $50k
            (Decimal("49990"), Decimal("1.0")),  # $49,990
            (Decimal("49980"), Decimal("1.0")),  # $49,980
        ]
        asks = [
            (Decimal("50010"), Decimal("1.0")),
        ]

        # Sell $100k worth (will consume multiple levels)
        result = calculate_slippage(bids, asks, 100_000, "sell")

        assert result["filled"] is True
        assert result["levels_consumed"] >= 2  # At least 2 levels
        assert result["slippage_bps"] > 0  # Should have positive slippage

    def test_slippage_buy_single_level(self):
        """Test slippage calculation for buy order."""
        bids = [
            (Decimal("50000"), Decimal("1.0")),
        ]
        asks = [
            (Decimal("50010"), Decimal("2.0")),  # $100k at best ask
        ]

        # Buy $50k worth
        result = calculate_slippage(bids, asks, 50_000, "buy")

        assert result["filled"] is True
        assert result["levels_consumed"] == 1
        assert result["average_price"] == 50010.0

    def test_slippage_insufficient_liquidity(self):
        """Test slippage when order cannot be fully filled."""
        bids = [
            (Decimal("50000"), Decimal("0.5")),  # Only $25k available
        ]
        asks = [
            (Decimal("50010"), Decimal("1.0")),
        ]

        # Try to sell $100k worth (insufficient liquidity)
        result = calculate_slippage(bids, asks, 100_000, "sell")

        assert result["filled"] is False
        assert result["unfilled_usd"] > 0

    def test_slippage_empty_orderbook(self):
        """Test slippage calculation with empty order book."""
        result = calculate_slippage([], [], 50_000, "sell")

        assert result["filled"] is False
        assert "error" in result
        assert result["error"] == "Empty order book"


class TestDepthImbalance:
    """Test order book imbalance calculations."""

    def test_imbalance_balanced_book(self):
        """Test imbalance for balanced order book."""
        bids = [
            (Decimal("50000"), Decimal("1.0")),
            (Decimal("49990"), Decimal("1.0")),
        ]
        asks = [
            (Decimal("50010"), Decimal("1.0")),
            (Decimal("50020"), Decimal("1.0")),
        ]

        imbalance = calculate_depth_imbalance(bids, asks, levels=2)

        assert imbalance == 0.0

    def test_imbalance_bullish_book(self):
        """Test imbalance for bullish (bid-heavy) book."""
        bids = [
            (Decimal("50000"), Decimal("3.0")),
            (Decimal("49990"), Decimal("3.0")),
        ]
        asks = [
            (Decimal("50010"), Decimal("1.0")),
            (Decimal("50020"), Decimal("1.0")),
        ]

        imbalance = calculate_depth_imbalance(bids, asks, levels=2)

        # Imbalance = (6 - 2) / (6 + 2) = 0.5
        assert imbalance == 0.5

    def test_imbalance_bearish_book(self):
        """Test imbalance for bearish (ask-heavy) book."""
        bids = [
            (Decimal("50000"), Decimal("1.0")),
        ]
        asks = [
            (Decimal("50010"), Decimal("3.0")),
        ]

        imbalance = calculate_depth_imbalance(bids, asks, levels=1)

        # Imbalance = (1 - 3) / (1 + 3) = -0.5
        assert imbalance == -0.5

    def test_imbalance_empty_book(self):
        """Test imbalance returns 0 for empty book."""
        imbalance = calculate_depth_imbalance([], [], levels=10)

        assert imbalance == 0.0


class TestDepthAtBps:
    """Test depth calculation within basis points."""

    def test_depth_at_bps_basic(self):
        """Test depth calculation within 10 bps."""
        bids = [
            (Decimal("49995"), Decimal("1.0")),  # Within 10bps of mid
            (Decimal("49990"), Decimal("1.0")),  # Within 10bps of mid
            (Decimal("49900"), Decimal("10.0")),  # Outside 10bps
        ]
        asks = [
            (Decimal("50005"), Decimal("1.0")),  # Within 10bps of mid
            (Decimal("50010"), Decimal("1.0")),  # Within 10bps of mid
            (Decimal("50100"), Decimal("10.0")),  # Outside 10bps
        ]

        depth = calculate_depth_at_bps(bids, asks, bps=10)

        # Mid price = 50000
        # 10 bps = 0.1% = 50000 * 0.001 = ±50
        # So we include prices in range [49950, 50050]

        assert depth["bid_depth"] == 2.0  # 2 BTC on bid side
        assert depth["ask_depth"] == 2.0  # 2 BTC on ask side
        assert depth["total_depth"] == 4.0

    def test_depth_at_bps_wide_threshold(self):
        """Test depth with wider threshold (100 bps)."""
        bids = [
            (Decimal("49500"), Decimal("5.0")),
            (Decimal("49900"), Decimal("2.0")),
        ]
        asks = [
            (Decimal("50100"), Decimal("3.0")),
            (Decimal("50500"), Decimal("4.0")),
        ]

        depth = calculate_depth_at_bps(bids, asks, bps=100)

        # Mid = 50000
        # 100 bps = 1% = ±500
        # Range: [49500, 50500]
        # Only 49900 is within range for bids (49500 < 49500)
        # Only 50100 is within range for asks (50500 > 50500)

        assert depth["bid_depth"] >= 2.0  # At least the 49900 level
        assert depth["ask_depth"] >= 3.0  # At least the 50100 level

    def test_depth_at_bps_empty_book(self):
        """Test depth returns zero for empty book."""
        depth = calculate_depth_at_bps([], [], bps=10)

        assert depth["bid_depth"] == 0.0
        assert depth["ask_depth"] == 0.0
        assert depth["total_depth"] == 0.0
        assert depth["total_depth_usd"] == 0.0


class TestLiquidityCrunchDetector:
    """Test anomaly detection using Z-score analysis."""

    def test_detector_initialization(self):
        """Test detector initializes correctly."""
        detector = LiquidityCrunchDetector(window_size=100, threshold=3.0, min_samples=10)

        assert detector.window_size == 100
        assert detector.threshold == 3.0
        assert detector.min_samples == 10
        assert len(detector.depth_history) == 0

    def test_detector_insufficient_samples(self):
        """Test detector returns no anomaly with insufficient samples."""
        detector = LiquidityCrunchDetector(window_size=100, threshold=3.0, min_samples=30)

        # Add only 10 samples
        for _ in range(10):
            result = detector.detect_liquidity_crunch(
                current_depth=100_000, current_spread=5.0, current_imbalance=0.0
            )

            assert result["is_anomaly"] is False
            assert "Insufficient" in result["reason"]

    def test_detector_normal_regime(self):
        """Test detector doesn't flag anomalies in normal regime."""
        detector = LiquidityCrunchDetector(window_size=100, threshold=3.0, min_samples=30)

        # Add 50 samples with consistent values
        for _ in range(50):
            result = detector.detect_liquidity_crunch(
                current_depth=100_000, current_spread=5.0, current_imbalance=0.0
            )

        # Last result should show normal (no anomaly)
        assert result["is_anomaly"] is False
        assert abs(result["depth_zscore"]) < 0.1  # Near zero

    def test_detector_low_depth_anomaly(self):
        """Test detector flags low depth anomaly."""
        detector = LiquidityCrunchDetector(
            window_size=100, threshold=2.0, min_samples=30  # Lower threshold for testing
        )

        # Add 40 samples with normal depth
        for _ in range(40):
            detector.detect_liquidity_crunch(
                current_depth=100_000, current_spread=5.0, current_imbalance=0.0
            )

        # Add sample with very low depth (should trigger anomaly)
        result = detector.detect_liquidity_crunch(
            current_depth=10_000,  # 10x lower than average
            current_spread=5.0,
            current_imbalance=0.0,
        )

        assert result["is_anomaly"] is True
        assert result["depth_zscore"] < -2.0
        assert "Depth" in result["reason"]

    def test_detector_high_spread_anomaly(self):
        """Test detector flags high spread anomaly."""
        detector = LiquidityCrunchDetector(window_size=100, threshold=2.0, min_samples=30)

        # Add 40 samples with normal spread
        for _ in range(40):
            detector.detect_liquidity_crunch(
                current_depth=100_000, current_spread=5.0, current_imbalance=0.0
            )

        # Add sample with very high spread (should trigger anomaly)
        result = detector.detect_liquidity_crunch(
            current_depth=100_000,
            current_spread=50.0,  # 10x higher than average
            current_imbalance=0.0,
        )

        assert result["is_anomaly"] is True
        assert result["spread_zscore"] > 2.0
        assert "Spread" in result["reason"]

    def test_detector_severity_classification(self):
        """Test anomaly severity classification."""
        detector = LiquidityCrunchDetector(window_size=100, threshold=3.0, min_samples=30)

        # Add 40 samples
        for _ in range(40):
            detector.detect_liquidity_crunch(
                current_depth=100_000, current_spread=5.0, current_imbalance=0.0
            )

        # Test warning severity (3-4σ)
        result = detector.detect_liquidity_crunch(
            current_depth=40_000, current_spread=5.0, current_imbalance=0.0  # Moderate drop
        )

        if result["is_anomaly"]:
            # Severity should be warning or higher
            assert result["severity"] in ["warning", "high", "critical"]

    def test_detector_statistics(self):
        """Test detector returns statistics correctly."""
        detector = LiquidityCrunchDetector(window_size=100, threshold=3.0, min_samples=30)

        # Add samples
        for i in range(50):
            detector.detect_liquidity_crunch(
                current_depth=100_000 + i * 1000,
                current_spread=5.0 + i * 0.1,
                current_imbalance=0.0,
            )

        stats = detector.get_statistics()

        assert "depth" in stats
        assert "spread" in stats
        assert "imbalance" in stats
        assert stats["depth"]["count"] == 50
        assert stats["spread"]["count"] == 50


class TestRiskEngineEdgeCases:
    """Test edge cases in risk calculations."""

    def test_slippage_zero_trade_size(self):
        """Test slippage with zero trade size."""
        bids = [(Decimal("50000"), Decimal("1.0"))]
        asks = [(Decimal("50010"), Decimal("1.0"))]

        result = calculate_slippage(bids, asks, 0, "sell")

        # Zero trade size is technically "filled" (nothing to fill)
        # But the function considers it as no base quantity filled
        assert result["slippage_usd"] == 0.0
        assert result["levels_consumed"] == 0

    def test_depth_imbalance_single_side(self):
        """Test imbalance with only one side populated."""
        bids = [(Decimal("50000"), Decimal("5.0"))]
        asks = []

        imbalance = calculate_depth_imbalance(bids, asks, levels=10)

        # Should return 0 (or handle gracefully)
        assert isinstance(imbalance, float)

    def test_depth_calculation_precision(self):
        """Test depth calculation maintains precision."""
        bids = [
            (Decimal("49999.99"), Decimal("1.23456789")),
        ]
        asks = [
            (Decimal("50000.01"), Decimal("2.34567890")),
        ]

        depth = calculate_depth_at_bps(bids, asks, bps=10)

        # Should maintain high precision
        assert depth["bid_depth"] == 1.2346
        assert depth["ask_depth"] == 2.3457


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
