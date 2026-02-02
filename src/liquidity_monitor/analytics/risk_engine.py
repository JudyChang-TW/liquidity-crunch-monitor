"""
Risk calculation engine for liquidity monitoring.

This module provides functions for:
- Slippage estimation for large orders
- Liquidity crunch detection using Z-score analysis
- Real-time risk metrics calculation
"""

import time
from collections import deque
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from ..core.orderbook import OrderBook
from ..utils.logger import get_logger

logger = get_logger(__name__)


def calculate_slippage(
    bids: List[Tuple[Decimal, Decimal]],
    asks: List[Tuple[Decimal, Decimal]],
    trade_size_usd: float,
    side: str = "sell",
) -> Dict[str, Union[float, int, bool, str]]:
    """
    Calculate slippage for a large market order by walking the order book.

    This function simulates executing a market order of given size and calculates:
    - Average execution price
    - Slippage in USD and basis points
    - Total cost/proceeds
    - Number of levels consumed

    Args:
        bids: List of (price, quantity) tuples for bids (highest to lowest)
        asks: List of (price, quantity) tuples for asks (lowest to highest)
        trade_size_usd: Order size in USD (e.g., 1_000_000 for $1M)
        side: "sell" (market sell) or "buy" (market buy)

    Returns:
        Dictionary with slippage metrics:
        {
            "average_price": float,
            "mid_price": float,
            "slippage_usd": float,
            "slippage_bps": float,
            "total_cost": float,
            "base_qty_filled": float,
            "levels_consumed": int,
            "filled": bool,
            "unfilled_usd": float,
            "error": str (optional, only present on error)
        }

    Example:
        >>> bids = [(Decimal("50000"), Decimal("1.0")), ...]
        >>> slippage = calculate_slippage(bids, [], 100000, "sell")
        >>> print(f"Slippage: {slippage['slippage_bps']:.2f} bps")
    """
    if not bids or not asks:
        return {
            "average_price": 0.0,
            "mid_price": 0.0,
            "slippage_usd": 0.0,
            "slippage_bps": 0.0,
            "total_cost": 0.0,
            "levels_consumed": 0,
            "filled": False,
            "unfilled_usd": trade_size_usd,
            "error": "Empty order book",
        }

    # Calculate mid-price
    best_bid_price = float(bids[0][0])
    best_ask_price = float(asks[0][0])
    mid_price = (best_bid_price + best_ask_price) / 2

    # Select appropriate side
    levels = bids if side == "sell" else asks

    # Walk the order book
    remaining_usd = trade_size_usd
    total_base_qty = 0.0  # Total quantity filled (in base currency, e.g., BTC)
    total_quote_received = 0.0  # Total quote currency received/paid (USD)
    levels_consumed = 0

    for idx, (price, qty) in enumerate(levels):
        if remaining_usd <= 0:
            break

        price_float = float(price)
        qty_float = float(qty)

        # Calculate how much we can fill at this level
        level_value_usd = price_float * qty_float

        if level_value_usd <= remaining_usd:
            # Consume entire level
            fill_qty = qty_float
            fill_value = level_value_usd
        else:
            # Partial fill (final level)
            fill_qty = remaining_usd / price_float
            fill_value = remaining_usd

        total_base_qty += fill_qty
        total_quote_received += fill_value
        remaining_usd -= fill_value
        levels_consumed = idx + 1

    # Check if order was fully filled
    filled = remaining_usd <= 0.01  # Allow small rounding errors

    if total_base_qty == 0:
        return {
            "average_price": 0.0,
            "mid_price": mid_price,
            "slippage_usd": 0.0,
            "slippage_bps": 0.0,
            "total_cost": 0.0,
            "levels_consumed": 0,
            "filled": False,
            "unfilled_usd": trade_size_usd,
            "error": "Insufficient liquidity",
        }

    # Calculate average execution price
    average_price = total_quote_received / total_base_qty

    # Calculate slippage
    if side == "sell":
        # For sells, we want higher prices (slippage is negative difference)
        slippage_usd = (mid_price - average_price) * total_base_qty
        slippage_bps = ((mid_price - average_price) / mid_price) * 10000
    else:
        # For buys, we want lower prices (slippage is positive difference)
        slippage_usd = (average_price - mid_price) * total_base_qty
        slippage_bps = ((average_price - mid_price) / mid_price) * 10000

    return {
        "average_price": round(average_price, 2),
        "mid_price": round(mid_price, 2),
        "slippage_usd": round(slippage_usd, 2),
        "slippage_bps": round(slippage_bps, 2),
        "total_cost": round(total_quote_received, 2),
        "base_qty_filled": round(total_base_qty, 4),
        "levels_consumed": levels_consumed,
        "filled": filled,
        "unfilled_usd": round(max(0, remaining_usd), 2),
    }


def calculate_depth_imbalance(
    bids: List[Tuple[Decimal, Decimal]], asks: List[Tuple[Decimal, Decimal]], levels: int = 10
) -> float:
    """
    Calculate order book imbalance ratio.

    Imbalance = (Bid Volume - Ask Volume) / (Bid Volume + Ask Volume)

    Args:
        bids: List of (price, quantity) tuples for bids
        asks: List of (price, quantity) tuples for asks
        levels: Number of levels to include in calculation

    Returns:
        Imbalance ratio in range [-1, +1]
        +1 = Only bids (bullish pressure)
        -1 = Only asks (bearish pressure)
         0 = Balanced
    """
    if not bids or not asks:
        return 0.0

    # Sum top N levels
    bid_volume = sum(float(qty) for _, qty in bids[:levels])
    ask_volume = sum(float(qty) for _, qty in asks[:levels])

    total_volume = bid_volume + ask_volume

    if total_volume == 0:
        return 0.0

    imbalance = (bid_volume - ask_volume) / total_volume
    return round(imbalance, 4)


def calculate_depth_at_bps(
    bids: List[Tuple[Decimal, Decimal]], asks: List[Tuple[Decimal, Decimal]], bps: int = 10
) -> Dict[str, float]:
    """
    Calculate total depth within X basis points of mid-price.

    Args:
        bids: List of (price, quantity) tuples for bids
        asks: List of (price, quantity) tuples for asks
        bps: Basis points from mid-price (e.g., 10 = 0.1%)

    Returns:
        Dictionary with depth metrics:
        {
            "bid_depth": float,  # Volume in base currency
            "ask_depth": float,
            "total_depth": float,
            "bid_depth_usd": float,  # Value in USD
            "ask_depth_usd": float,
            "total_depth_usd": float
        }
    """
    if not bids or not asks:
        return {
            "bid_depth": 0.0,
            "ask_depth": 0.0,
            "total_depth": 0.0,
            "bid_depth_usd": 0.0,
            "ask_depth_usd": 0.0,
            "total_depth_usd": 0.0,
        }

    # Calculate mid-price
    mid_price = (float(bids[0][0]) + float(asks[0][0])) / 2
    threshold = bps / 10000  # Convert bps to decimal

    # Calculate bid-side depth
    bid_depth = 0.0
    bid_depth_usd = 0.0
    for price, qty in bids:
        price_float = float(price)
        qty_float = float(qty)

        if price_float >= mid_price * (1 - threshold):
            bid_depth += qty_float
            bid_depth_usd += price_float * qty_float
        else:
            break

    # Calculate ask-side depth
    ask_depth = 0.0
    ask_depth_usd = 0.0
    for price, qty in asks:
        price_float = float(price)
        qty_float = float(qty)

        if price_float <= mid_price * (1 + threshold):
            ask_depth += qty_float
            ask_depth_usd += price_float * qty_float
        else:
            break

    return {
        "bid_depth": round(bid_depth, 4),
        "ask_depth": round(ask_depth, 4),
        "total_depth": round(bid_depth + ask_depth, 4),
        "bid_depth_usd": round(bid_depth_usd, 2),
        "ask_depth_usd": round(ask_depth_usd, 2),
        "total_depth_usd": round(bid_depth_usd + ask_depth_usd, 2),
    }


class LiquidityCrunchDetector:
    """
    Detects liquidity anomalies using Z-score analysis.

    Monitors depth and spread metrics over a rolling window and flags
    anomalies when values deviate significantly from historical norms.

    Example:
        >>> detector = LiquidityCrunchDetector(window_size=300, threshold=3.0)
        >>> anomaly = detector.detect_liquidity_crunch(current_depth=50000)
        >>> if anomaly['is_anomaly']:
        ...     print(f"ALERT: {anomaly['reason']}")
    """

    def __init__(self, window_size: int = 300, threshold: float = 3.0, min_samples: int = 30):
        """
        Initialize liquidity crunch detector.

        Args:
            window_size: Number of samples to keep in rolling window
            threshold: Z-score threshold for anomaly detection (e.g., 3.0 = 3 std dev)
            min_samples: Minimum samples required before detecting anomalies
        """
        self.window_size = window_size
        self.threshold = threshold
        self.min_samples = min_samples

        # Rolling windows for metrics
        self.depth_history: deque[float] = deque(maxlen=window_size)
        self.spread_history: deque[float] = deque(maxlen=window_size)
        self.imbalance_history: deque[float] = deque(maxlen=window_size)

        logger.info(
            "detector_initialized",
            window_size=window_size,
            threshold=threshold,
            min_samples=min_samples,
        )

    def detect_liquidity_crunch(
        self,
        current_depth: float,
        current_spread: Optional[float] = None,
        current_imbalance: Optional[float] = None,
    ) -> Dict[str, Union[bool, float, str]]:
        """
        Detect if current liquidity metrics indicate a crunch.

        Uses Z-score analysis: Z = (X - μ) / σ
        Anomaly flagged if |Z| > threshold

        Args:
            current_depth: Current market depth (e.g., USD value)
            current_spread: Current spread in basis points (optional)
            current_imbalance: Current order book imbalance (optional)

        Returns:
            Dictionary with detection results:
            {
                "is_anomaly": bool,
                "depth_zscore": float,
                "spread_zscore": float,
                "imbalance_zscore": float,
                "reason": str,
                "severity": str,  # "none", "warning", "critical"
                "timestamp": float
            }
        """
        # Add current values to history
        self.depth_history.append(current_depth)
        if current_spread is not None:
            self.spread_history.append(current_spread)
        if current_imbalance is not None:
            self.imbalance_history.append(current_imbalance)

        # Need minimum samples for statistical significance
        if len(self.depth_history) < self.min_samples:
            return {
                "is_anomaly": False,
                "depth_zscore": 0.0,
                "spread_zscore": 0.0,
                "imbalance_zscore": 0.0,
                "reason": "Insufficient historical data",
                "severity": "none",
                "timestamp": time.time(),
            }

        # Calculate Z-scores
        depth_zscore = self._calculate_zscore(self.depth_history, current_depth)
        spread_zscore = (
            self._calculate_zscore(self.spread_history, current_spread) if current_spread else 0.0
        )
        imbalance_zscore = (
            self._calculate_zscore(self.imbalance_history, current_imbalance)
            if current_imbalance
            else 0.0
        )

        # Detect anomalies
        anomalies = []
        max_zscore = 0.0

        # Low depth is concerning (negative Z-score)
        if depth_zscore < -self.threshold:
            anomalies.append(f"Depth {abs(depth_zscore):.1f}σ below average")
            max_zscore = abs(depth_zscore)

        # High spread is concerning (positive Z-score)
        if spread_zscore > self.threshold:
            anomalies.append(f"Spread {spread_zscore:.1f}σ above average")
            max_zscore = max(max_zscore, spread_zscore)

        # Extreme imbalance is concerning
        if abs(imbalance_zscore) > self.threshold:
            anomalies.append(f"Imbalance {abs(imbalance_zscore):.1f}σ from normal")
            max_zscore = max(max_zscore, abs(imbalance_zscore))

        # Determine severity
        if max_zscore >= 5.0:
            severity = "critical"
        elif max_zscore >= 4.0:
            severity = "high"
        elif max_zscore >= self.threshold:
            severity = "warning"
        else:
            severity = "none"

        is_anomaly = len(anomalies) > 0

        if is_anomaly:
            logger.warning(
                "liquidity_anomaly_detected",
                depth_zscore=round(depth_zscore, 2),
                spread_zscore=round(spread_zscore, 2),
                imbalance_zscore=round(imbalance_zscore, 2),
                severity=severity,
                anomalies=anomalies,
            )

        return {
            "is_anomaly": is_anomaly,
            "depth_zscore": round(depth_zscore, 2),
            "spread_zscore": round(spread_zscore, 2),
            "imbalance_zscore": round(imbalance_zscore, 2),
            "reason": "; ".join(anomalies) if anomalies else "Normal",
            "severity": severity,
            "timestamp": time.time(),
            "max_zscore": round(max_zscore, 2),
        }

    def _calculate_zscore(self, history: deque[float], current_value: Optional[float]) -> float:
        """
        Calculate Z-score for current value against historical data.

        Z = (X - μ) / σ

        Args:
            history: Historical values
            current_value: Current value to compare

        Returns:
            Z-score (0.0 if calculation not possible)
        """
        if current_value is None or len(history) < self.min_samples:
            return 0.0

        arr = np.array(history)
        mean = np.mean(arr)
        std = np.std(arr)

        if std == 0:
            return 0.0

        zscore: float = float((current_value - mean) / std)
        return zscore

    def get_statistics(self) -> Dict[str, Dict[str, Union[float, int]]]:
        """
        Get current statistics for all monitored metrics.

        Returns:
            Dictionary with mean, std, min, max for each metric
        """

        def calc_stats(history: deque[float]) -> Dict[str, Union[float, int]]:
            if len(history) == 0:
                return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "count": 0}

            arr = np.array(history)
            return {
                "mean": round(float(np.mean(arr)), 2),
                "std": round(float(np.std(arr)), 2),
                "min": round(float(np.min(arr)), 2),
                "max": round(float(np.max(arr)), 2),
                "count": len(history),
            }

        return {
            "depth": calc_stats(self.depth_history),
            "spread": calc_stats(self.spread_history),
            "imbalance": calc_stats(self.imbalance_history),
        }


class RiskEngine:
    """
    Orchestrates risk calculations and anomaly detection.

    This class combines order book data with risk analytics to provide
    comprehensive liquidity monitoring.

    Example:
        >>> engine = RiskEngine(orderbook_manager)
        >>> metrics = await engine.calculate_metrics()
        >>> print(metrics)
    """

    def __init__(
        self,
        orderbook: OrderBook,
        slippage_sizes_usd: Optional[List[float]] = None,
        depth_bps: Optional[List[int]] = None,
        detector_window: int = 300,
        detector_threshold: float = 3.0,
    ):
        """
        Initialize risk engine.

        Args:
            orderbook: OrderBook instance to monitor
            slippage_sizes_usd: List of order sizes to calculate slippage for
                               (defaults to [100_000, 500_000, 1_000_000])
            depth_bps: List of basis point thresholds for depth calculation
                      (defaults to [10, 50, 100])
            detector_window: Rolling window size for anomaly detection
            detector_threshold: Z-score threshold for anomalies
        """
        self.orderbook = orderbook

        # Avoid mutable default arguments (B006)
        # Each instance gets a fresh list to prevent data pollution
        if slippage_sizes_usd is None:
            slippage_sizes_usd = [100_000, 500_000, 1_000_000]
        if depth_bps is None:
            depth_bps = [10, 50, 100]

        self.slippage_sizes_usd = slippage_sizes_usd
        self.depth_bps = depth_bps

        # Initialize detector
        self.detector = LiquidityCrunchDetector(
            window_size=detector_window, threshold=detector_threshold
        )

        logger.info(
            "risk_engine_initialized",
            symbol=orderbook.symbol,
            slippage_sizes=slippage_sizes_usd,
            depth_bps=depth_bps,
        )

    def calculate_metrics(self) -> Dict[str, Any]:
        """
        Calculate comprehensive risk metrics from current order book state.

        Returns:
            Dictionary with all calculated metrics:
            {
                "basic": {...},       # Basic metrics (spread, mid-price)
                "slippage": {...},    # Slippage for different sizes
                "depth": {...},       # Depth at different bps
                "imbalance": float,   # Order book imbalance
                "anomaly": {...},     # Anomaly detection results
                "timestamp": float
            }
        """
        # Get order book depth
        depth_data = self.orderbook.get_depth(levels=50)
        bids = depth_data["bids"]
        asks = depth_data["asks"]

        if not bids or not asks:
            return {"error": "Empty order book", "timestamp": time.time()}

        # Basic metrics
        mid_price = self.orderbook.get_mid_price()
        spread_bps = self.orderbook.get_spread_bps()

        basic_metrics = {
            "mid_price": float(mid_price) if mid_price else 0.0,
            "spread_bps": float(spread_bps) if spread_bps else 0.0,
            "bid_levels": len(self.orderbook.bids),
            "ask_levels": len(self.orderbook.asks),
        }

        # Slippage calculation for multiple sizes
        slippage_metrics = {}
        for size_usd in self.slippage_sizes_usd:
            sell_slippage = calculate_slippage(bids, asks, size_usd, "sell")
            slippage_metrics[f"sell_{int(size_usd / 1000)}k"] = sell_slippage

        # Depth calculation at different thresholds
        depth_metrics = {}
        for bps in self.depth_bps:
            depth = calculate_depth_at_bps(bids, asks, bps)
            depth_metrics[f"{bps}bps"] = depth

        # Order book imbalance
        imbalance = calculate_depth_imbalance(bids, asks, levels=10)

        # Anomaly detection
        # Use 10bps depth as primary metric
        primary_depth = depth_metrics.get("10bps", {}).get("total_depth_usd", 0.0)
        anomaly = self.detector.detect_liquidity_crunch(
            current_depth=primary_depth,
            current_spread=basic_metrics["spread_bps"],
            current_imbalance=imbalance,
        )

        return {
            "basic": basic_metrics,
            "slippage": slippage_metrics,
            "depth": depth_metrics,
            "imbalance": imbalance,
            "anomaly": anomaly,
            "timestamp": time.time(),
        }
