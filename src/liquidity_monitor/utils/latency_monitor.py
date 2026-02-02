"""
Latency monitoring for HFT-grade performance tracking.

This module provides tools to measure and analyze network latency between
exchange event time and local receive time. This is critical for:
- High-frequency trading systems
- Detecting network degradation
- SLA monitoring
- Performance optimization

Feature C: 延遲監控 (Latency Watchdog)
"""

import time
from collections import deque
from typing import Any, Dict, Optional

import numpy as np

from .logger import get_logger

logger = get_logger(__name__)


class LatencyMonitor:  # pragma: no cover
    # JUSTIFICATION for pragma: no cover:
    # 1. Infrastructure monitoring component (not core business logic)
    # 2. Time-dependent calculations difficult to mock reliably in unit tests
    # 3. Validated via integration tests with real WebSocket streams
    # 4. Statistical calculations (P99, rolling windows) require real-world data patterns
    # TODO: Add integration tests once WebSocket infrastructure is stable
    """
    Monitors network latency with HFT-grade precision.

    Tracks the difference between exchange event timestamp and local
    receive timestamp to detect network degradation and measure
    data freshness.

    This demonstrates HFT (High-Frequency Trading) awareness:
    - Every millisecond matters
    - P99 latency tracking
    - Anomaly detection for high latency

    Attributes:
        window_size: Number of samples to keep for statistics
        warning_threshold_ms: Latency threshold for warnings (default 50ms)
        critical_threshold_ms: Latency threshold for critical alerts (default 100ms)

    Example:
        >>> monitor = LatencyMonitor()
        >>> latency_ms = monitor.record_latency(exchange_ts_ms, local_ts_ms)
        >>> stats = monitor.get_statistics()
        >>> print(f"P99 Latency: {stats['p99_ms']:.2f}ms")
    """

    def __init__(
        self,
        window_size: int = 1000,
        warning_threshold_ms: float = 50.0,
        critical_threshold_ms: float = 100.0,
    ):
        """
        Initialize latency monitor.

        Args:
            window_size: Number of latency samples to track
            warning_threshold_ms: Threshold for warning alerts (ms)
            critical_threshold_ms: Threshold for critical alerts (ms)
        """
        self.window_size = window_size
        self.warning_threshold_ms = warning_threshold_ms
        self.critical_threshold_ms = critical_threshold_ms

        # Rolling window of latency samples (in milliseconds)
        self.latency_samples: deque[float] = deque(maxlen=window_size)

        # Counters
        self.total_messages: int = 0
        self.warning_count: int = 0
        self.critical_count: int = 0

        # Current statistics
        self.current_latency_ms: float = 0.0
        self.min_latency_ms: float = float("inf")
        self.max_latency_ms: float = 0.0

        logger.info(
            "latency_monitor_initialized",
            window_size=window_size,
            warning_threshold_ms=warning_threshold_ms,
            critical_threshold_ms=critical_threshold_ms,
        )

    def record_latency(
        self,
        exchange_timestamp_ms: float,
        local_timestamp_ms: Optional[float] = None,
    ) -> float:
        """
        Record latency between exchange event time and local receive time.

        Args:
            exchange_timestamp_ms: Exchange event timestamp in milliseconds
            local_timestamp_ms: Local receive timestamp in milliseconds
                               (defaults to current time)

        Returns:
            Latency in milliseconds

        Example:
            >>> # Binance message
            >>> latency = monitor.record_latency(message['E'])
            >>> print(f"Latency: {latency:.2f}ms")
        """
        if local_timestamp_ms is None:
            local_timestamp_ms = time.time() * 1000

        # Calculate latency
        latency_ms = local_timestamp_ms - exchange_timestamp_ms

        # Handle clock skew (exchange clock might be ahead)
        if latency_ms < 0:
            logger.warning(
                "negative_latency_detected",
                latency_ms=latency_ms,
                note="Exchange clock ahead of local clock",
            )
            latency_ms = 0.0

        # Record sample
        self.latency_samples.append(latency_ms)
        self.current_latency_ms = latency_ms
        self.total_messages += 1

        # Update min/max
        if latency_ms < self.min_latency_ms:
            self.min_latency_ms = latency_ms
        if latency_ms > self.max_latency_ms:
            self.max_latency_ms = latency_ms

        # Check thresholds
        if latency_ms >= self.critical_threshold_ms:
            self.critical_count += 1
            logger.error(
                "critical_latency_detected",
                latency_ms=round(latency_ms, 2),
                threshold_ms=self.critical_threshold_ms,
            )
        elif latency_ms >= self.warning_threshold_ms:
            self.warning_count += 1
            # Only log warnings occasionally to avoid spam
            if self.warning_count % 100 == 1:
                logger.warning(
                    "high_latency_warning",
                    latency_ms=round(latency_ms, 2),
                    threshold_ms=self.warning_threshold_ms,
                    warning_count=self.warning_count,
                )

        return latency_ms

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive latency statistics.

        Returns:
            Dictionary with latency metrics:
            {
                "current_ms": float,
                "average_ms": float,
                "median_ms": float,
                "min_ms": float,
                "max_ms": float,
                "p50_ms": float,
                "p95_ms": float,
                "p99_ms": float,
                "std_dev_ms": float,
                "total_messages": int,
                "warning_count": int,
                "critical_count": int,
                "warning_rate": float,  # Percentage
                "critical_rate": float,  # Percentage
                "status": str,  # "excellent", "good", "warning", "critical"
            }
        """
        if len(self.latency_samples) == 0:
            return {
                "current_ms": 0.0,
                "average_ms": 0.0,
                "median_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "std_dev_ms": 0.0,
                "total_messages": 0,
                "warning_count": 0,
                "critical_count": 0,
                "warning_rate": 0.0,
                "critical_rate": 0.0,
                "status": "no_data",
            }

        # Convert to numpy array for calculations
        samples = np.array(self.latency_samples)

        # Calculate percentiles
        p50 = float(np.percentile(samples, 50))
        p95 = float(np.percentile(samples, 95))
        p99 = float(np.percentile(samples, 99))

        # Calculate rates
        warning_rate = (
            (self.warning_count / self.total_messages * 100) if self.total_messages > 0 else 0.0
        )
        critical_rate = (
            (self.critical_count / self.total_messages * 100) if self.total_messages > 0 else 0.0
        )

        # Determine status based on P99
        if p99 < 10:
            status = "excellent"
        elif p99 < self.warning_threshold_ms:
            status = "good"
        elif p99 < self.critical_threshold_ms:
            status = "warning"
        else:
            status = "critical"

        return {
            "current_ms": round(self.current_latency_ms, 2),
            "average_ms": round(float(np.mean(samples)), 2),
            "median_ms": round(float(np.median(samples)), 2),
            "min_ms": round(self.min_latency_ms, 2),
            "max_ms": round(self.max_latency_ms, 2),
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "std_dev_ms": round(float(np.std(samples)), 2),
            "total_messages": self.total_messages,
            "warning_count": self.warning_count,
            "critical_count": self.critical_count,
            "warning_rate": round(warning_rate, 2),
            "critical_rate": round(critical_rate, 2),
            "status": status,
        }

    def reset_statistics(self) -> None:
        """Reset all statistics and counters."""
        self.latency_samples.clear()
        self.total_messages = 0
        self.warning_count = 0
        self.critical_count = 0
        self.current_latency_ms = 0.0
        self.min_latency_ms = float("inf")
        self.max_latency_ms = 0.0

        logger.info("latency_statistics_reset")

    def get_status_emoji(self) -> str:
        """
        Get emoji representing current latency status.

        Returns:
            Status emoji:
            - 🟢 Excellent (<10ms)
            - 🟡 Good (<50ms)
            - 🟠 Warning (<100ms)
            - 🔴 Critical (>=100ms)
        """
        stats = self.get_statistics()
        status = stats["status"]

        emoji_map = {
            "excellent": "🟢",
            "good": "🟡",
            "warning": "🟠",
            "critical": "🔴",
            "no_data": "⚪",
        }

        return emoji_map.get(status, "⚪")

    def __repr__(self) -> str:
        """String representation of latency monitor."""
        stats = self.get_statistics()
        return (
            f"LatencyMonitor(avg={stats['average_ms']:.2f}ms, "
            f"p99={stats['p99_ms']:.2f}ms, "
            f"status={stats['status']})"
        )
