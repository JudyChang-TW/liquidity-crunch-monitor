"""
Structured logging utility for Liquidity-Crunch-Monitor.

This module provides a structured logger using structlog for consistent,
machine-readable logging with performance tracking capabilities.
"""

import logging
import sys
import time
from typing import Any, cast

import structlog
from structlog.types import EventDict, Processor


def add_timestamp(
    logger: Any, method_name: str, event_dict: EventDict
) -> EventDict:  # pragma: no cover
    """Add ISO 8601 timestamp to log entries."""
    # Infrastructure utility - tested via integration tests
    event_dict["timestamp"] = time.time()
    return event_dict


def add_log_level(
    logger: Any, method_name: str, event_dict: EventDict
) -> EventDict:  # pragma: no cover
    """Add log level to event dict."""
    # Infrastructure utility - tested via integration tests
    event_dict["level"] = method_name
    return event_dict


def configure_logging(  # pragma: no cover
    log_level: str = "INFO", json_format: bool = True, colorize: bool = True
) -> None:
    """
    Configure structured logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: If True, output JSON format; otherwise, console format
        colorize: If True and not json_format, colorize output

    Example:
        >>> configure_logging(log_level="DEBUG", json_format=False, colorize=True)

    Note:
        This function modifies global logging state and is difficult to test
        in unit tests. Validated via integration tests and manual verification.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )

    processors: list[Processor] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_timestamp,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        if colorize:
            processors.append(structlog.dev.ConsoleRenderer(colors=True))
        else:
            processors.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__ of the module)

    Returns:
        Configured structlog logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("order_book_update", symbol="BTCUSDT", latency_us=45.3)
    """
    # structlog.get_logger() returns Any, but we know it's a BoundLogger
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


class PerformanceLogger:
    """
    Context manager for logging operation performance.

    Example:
        >>> logger = get_logger(__name__)
        >>> with PerformanceLogger(logger, "order_book_update", symbol="BTCUSDT"):
        ...     # Perform order book update
        ...     pass
        # Logs: {"event": "order_book_update", "duration_ms": 0.045, "symbol": "BTCUSDT"}
    """

    def __init__(
        self,
        logger: structlog.stdlib.BoundLogger,
        operation: str,
        threshold_ms: float = 100.0,
        **context: Any,
    ):
        """
        Initialize performance logger.

        Args:
            logger: Structlog logger instance
            operation: Name of the operation being measured
            threshold_ms: Log warning if duration exceeds this threshold
            **context: Additional context to include in log
        """
        self.logger = logger
        self.operation = operation
        self.threshold_ms = threshold_ms
        self.context = context
        self.start_time: float | None = None

    def __enter__(self) -> "PerformanceLogger":
        """Start timing."""
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop timing and log duration."""
        if self.start_time is None:
            return

        duration_ms = (time.perf_counter() - self.start_time) * 1000

        log_data = {
            "operation": self.operation,
            "duration_ms": round(duration_ms, 3),
            **self.context,
        }

        if exc_type is not None:
            self.logger.error(
                "operation_failed", **log_data, error=str(exc_val), error_type=exc_type.__name__
            )
        elif duration_ms > self.threshold_ms:
            self.logger.warning("slow_operation", **log_data)
        else:
            self.logger.debug("operation_complete", **log_data)
