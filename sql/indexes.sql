-- Performance Indexes for Liquidity Monitor Database
-- PostgreSQL 16+
--
-- These indexes optimize common query patterns for risk analysis.

-- ============================================================================
-- INDEXES: liquidity_snapshots
-- ============================================================================

-- Time-series queries (most common access pattern)
CREATE INDEX idx_snapshots_timestamp ON liquidity_snapshots(timestamp DESC);
CREATE INDEX idx_snapshots_symbol_timestamp ON liquidity_snapshots(symbol, timestamp DESC);

-- Symbol-based queries
CREATE INDEX idx_snapshots_symbol ON liquidity_snapshots(symbol);

-- Date range queries (for daily reports)
CREATE INDEX idx_snapshots_date ON liquidity_snapshots(DATE(timestamp));

-- Low depth detection (risk alerts)
CREATE INDEX idx_snapshots_low_depth ON liquidity_snapshots(depth_10bps_usd)
WHERE depth_10bps_usd < 100000;

-- High spread detection (illiquidity)
CREATE INDEX idx_snapshots_high_spread ON liquidity_snapshots(spread_bps)
WHERE spread_bps > 50;

-- ============================================================================
-- INDEXES: anomaly_events
-- ============================================================================

-- Time-series queries
CREATE INDEX idx_anomalies_detected_at ON anomaly_events(detected_at DESC);
CREATE INDEX idx_anomalies_symbol_detected_at ON anomaly_events(symbol, detected_at DESC);

-- Severity-based queries (critical events first)
CREATE INDEX idx_anomalies_severity ON anomaly_events(severity, detected_at DESC);

-- Symbol-based queries
CREATE INDEX idx_anomalies_symbol ON anomaly_events(symbol);

-- High severity alerts (for dashboards)
CREATE INDEX idx_anomalies_critical ON anomaly_events(detected_at DESC)
WHERE severity IN ('high', 'critical');

-- Z-score analysis
CREATE INDEX idx_anomalies_max_zscore ON anomaly_events(max_zscore DESC);

-- ============================================================================
-- INDEXES: risk_metrics_daily
-- ============================================================================

-- Date-based queries (most common for reports)
CREATE INDEX idx_daily_report_date ON risk_metrics_daily(report_date DESC);
CREATE INDEX idx_daily_symbol_date ON risk_metrics_daily(symbol, report_date DESC);

-- Symbol-based queries
CREATE INDEX idx_daily_symbol ON risk_metrics_daily(symbol);

-- ============================================================================
-- ANALYZE
-- ============================================================================

-- Update table statistics for query planner
ANALYZE liquidity_snapshots;
ANALYZE anomaly_events;
ANALYZE risk_metrics_daily;
