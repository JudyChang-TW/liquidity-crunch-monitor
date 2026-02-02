-- Liquidity Monitor Database Schema
-- PostgreSQL 16+
--
-- This schema stores real-time liquidity monitoring data for crypto markets.
-- Designed for risk analysis and post-trade reporting.

-- Extension for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- TABLE: liquidity_snapshots
-- ============================================================================
-- Stores per-minute snapshots of market liquidity metrics.
-- Used for:
-- - Historical trend analysis
-- - Regulatory reporting
-- - Risk dashboard visualization (Grafana/Tableau)
-- ============================================================================

CREATE TABLE IF NOT EXISTS liquidity_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,

    -- Market identification
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(50) DEFAULT 'binance_futures' NOT NULL,

    -- Timestamp (UTC)
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Basic market metrics
    mid_price NUMERIC(20, 8) NOT NULL,
    spread_bps NUMERIC(10, 4) NOT NULL,
    bid_levels INTEGER NOT NULL,
    ask_levels INTEGER NOT NULL,

    -- Depth metrics (USD values)
    depth_10bps_usd NUMERIC(20, 2),
    depth_50bps_usd NUMERIC(20, 2),
    depth_100bps_usd NUMERIC(20, 2),

    -- Depth metrics (base currency)
    depth_10bps NUMERIC(20, 8),
    depth_50bps NUMERIC(20, 8),
    depth_100bps NUMERIC(20, 8),

    -- Order book imbalance (-1 to +1)
    imbalance NUMERIC(6, 4),

    -- Slippage metrics for market sell orders
    slippage_100k_bps NUMERIC(10, 4),
    slippage_100k_usd NUMERIC(20, 2),
    slippage_500k_bps NUMERIC(10, 4),
    slippage_500k_usd NUMERIC(20, 2),
    slippage_1m_bps NUMERIC(10, 4),
    slippage_1m_usd NUMERIC(20, 2),

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- TABLE: anomaly_events
-- ============================================================================
-- Stores detected liquidity anomalies and risk events.
-- Used for:
-- - Real-time alerting
-- - Risk incident investigation
-- - Model validation and tuning
-- ============================================================================

CREATE TABLE IF NOT EXISTS anomaly_events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,

    -- Market identification
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(50) DEFAULT 'binance_futures' NOT NULL,

    -- Event timing
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Anomaly classification
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('warning', 'high', 'critical')),
    reason TEXT NOT NULL,

    -- Statistical metrics
    depth_zscore NUMERIC(10, 4),
    spread_zscore NUMERIC(10, 4),
    imbalance_zscore NUMERIC(10, 4),
    max_zscore NUMERIC(10, 4) NOT NULL,

    -- Market state at detection
    mid_price NUMERIC(20, 8) NOT NULL,
    spread_bps NUMERIC(10, 4) NOT NULL,
    depth_10bps_usd NUMERIC(20, 2),
    imbalance NUMERIC(6, 4),

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- TABLE: risk_metrics_daily
-- ============================================================================
-- Daily aggregated risk metrics for reporting.
-- Populated by scheduled jobs or manual queries.
-- ============================================================================

CREATE TABLE IF NOT EXISTS risk_metrics_daily (
    id BIGSERIAL PRIMARY KEY,

    -- Date identification
    report_date DATE NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(50) DEFAULT 'binance_futures' NOT NULL,

    -- Aggregated metrics
    avg_spread_bps NUMERIC(10, 4),
    max_spread_bps NUMERIC(10, 4),
    min_spread_bps NUMERIC(10, 4),

    avg_depth_10bps_usd NUMERIC(20, 2),
    min_depth_10bps_usd NUMERIC(20, 2),

    avg_slippage_100k_bps NUMERIC(10, 4),
    avg_slippage_500k_bps NUMERIC(10, 4),
    avg_slippage_1m_bps NUMERIC(10, 4),

    avg_imbalance NUMERIC(6, 4),

    -- Anomaly counts
    total_anomalies INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,
    high_count INTEGER DEFAULT 0,
    critical_count INTEGER DEFAULT 0,

    -- Sample counts
    total_snapshots INTEGER NOT NULL,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint: one report per day per symbol
    UNIQUE(report_date, symbol, exchange)
);

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE liquidity_snapshots IS 'Per-minute liquidity metrics for historical analysis and reporting';
COMMENT ON TABLE anomaly_events IS 'Detected liquidity anomalies and risk events for alerting';
COMMENT ON TABLE risk_metrics_daily IS 'Daily aggregated risk metrics for executive reporting';

COMMENT ON COLUMN liquidity_snapshots.spread_bps IS 'Bid-ask spread in basis points (10000 bps = 100%)';
COMMENT ON COLUMN liquidity_snapshots.imbalance IS 'Order book imbalance: +1 = bullish, -1 = bearish';
COMMENT ON COLUMN anomaly_events.severity IS 'Anomaly severity: warning (3-4σ), high (4-5σ), critical (>5σ)';
COMMENT ON COLUMN anomaly_events.max_zscore IS 'Maximum absolute Z-score across all metrics';
