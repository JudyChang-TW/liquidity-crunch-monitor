"""
Database module for PostgreSQL persistence.

This module provides async database operations using asyncpg for high-performance,
non-blocking writes to PostgreSQL. Designed for production HFT environments where
blocking I/O would degrade event loop performance.
"""

from .writer import DatabaseWriter

__all__ = ["DatabaseWriter"]
