-- ============================================================================
-- DAILY RISK SUMMARY REPORT
-- ============================================================================
-- Query: Calculate daily average slippage and risk metrics
-- Purpose: Generate executive summary for trading desk risk reporting
-- Author: Risk Analytics Team
-- Usage: psql -U risk_analyst -d liquidity_monitor -f query_daily_risk_summary.sql
-- ============================================================================

-- Set timezone to UTC for consistent reporting
SET timezone = 'UTC';

-- ============================================================================
-- QUERY 1: Daily Average Slippage by Symbol
-- ============================================================================
-- Calculates average slippage (bps) for different order sizes
-- Filters: Last 7 days
-- ============================================================================

SELECT
    symbol,
    DATE(timestamp) AS trade_date,

    -- Market conditions
    ROUND(AVG(mid_price)::numeric, 2) AS avg_mid_price,
    ROUND(AVG(spread_bps)::numeric, 2) AS avg_spread_bps,
    ROUND(MAX(spread_bps)::numeric, 2) AS max_spread_bps,

    -- Average slippage (basis points)
    ROUND(AVG(slippage_100k_bps)::numeric, 2) AS avg_slippage_100k_bps,
    ROUND(AVG(slippage_500k_bps)::numeric, 2) AS avg_slippage_500k_bps,
    ROUND(AVG(slippage_1m_bps)::numeric, 2) AS avg_slippage_1m_bps,

    -- Average slippage cost (USD)
    ROUND(AVG(slippage_100k_usd)::numeric, 0) AS avg_slippage_100k_usd,
    ROUND(AVG(slippage_500k_usd)::numeric, 0) AS avg_slippage_500k_usd,
    ROUND(AVG(slippage_1m_usd)::numeric, 0) AS avg_slippage_1m_usd,

    -- Market depth
    ROUND(AVG(depth_10bps_usd)::numeric, 0) AS avg_depth_10bps_usd,
    ROUND(MIN(depth_10bps_usd)::numeric, 0) AS min_depth_10bps_usd,

    -- Order book imbalance
    ROUND(AVG(imbalance)::numeric, 4) AS avg_imbalance,

    -- Sample size
    COUNT(*) AS snapshot_count

FROM liquidity_snapshots
WHERE
    timestamp >= CURRENT_DATE - INTERVAL '7 days'
    AND timestamp < CURRENT_DATE + INTERVAL '1 day'
GROUP BY
    symbol,
    DATE(timestamp)
ORDER BY
    trade_date DESC,
    symbol;

-- ============================================================================
-- QUERY 2: Daily Anomaly Summary
-- ============================================================================
-- Counts anomaly events by severity
-- Identifies most problematic trading periods
-- ============================================================================

\echo '\n\n=== DAILY ANOMALY SUMMARY ==='

SELECT
    symbol,
    DATE(detected_at) AS event_date,

    -- Anomaly counts by severity
    COUNT(*) AS total_anomalies,
    SUM(CASE WHEN severity = 'warning' THEN 1 ELSE 0 END) AS warning_count,
    SUM(CASE WHEN severity = 'high' THEN 1 ELSE 0 END) AS high_count,
    SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) AS critical_count,

    -- Statistical metrics
    ROUND(AVG(max_zscore)::numeric, 2) AS avg_max_zscore,
    ROUND(MAX(max_zscore)::numeric, 2) AS peak_zscore,

    -- Market impact
    ROUND(AVG(spread_bps)::numeric, 2) AS avg_spread_during_anomaly,
    ROUND(AVG(depth_10bps_usd)::numeric, 0) AS avg_depth_during_anomaly,

    -- Most common reasons
    MODE() WITHIN GROUP (ORDER BY reason) AS most_common_reason

FROM anomaly_events
WHERE
    detected_at >= CURRENT_DATE - INTERVAL '7 days'
    AND detected_at < CURRENT_DATE + INTERVAL '1 day'
GROUP BY
    symbol,
    DATE(detected_at)
ORDER BY
    event_date DESC,
    total_anomalies DESC;

-- ============================================================================
-- QUERY 3: Hourly Risk Profile (Today)
-- ============================================================================
-- Identifies riskiest trading hours
-- Useful for adjusting trading schedules
-- ============================================================================

\echo '\n\n=== HOURLY RISK PROFILE (TODAY) ==='

SELECT
    symbol,
    EXTRACT(HOUR FROM timestamp) AS hour_utc,

    -- Average metrics
    ROUND(AVG(spread_bps)::numeric, 2) AS avg_spread_bps,
    ROUND(AVG(depth_10bps_usd)::numeric, 0) AS avg_depth_usd,
    ROUND(AVG(slippage_500k_bps)::numeric, 2) AS avg_slippage_500k_bps,

    -- Worst-case scenarios
    ROUND(MAX(spread_bps)::numeric, 2) AS worst_spread_bps,
    ROUND(MIN(depth_10bps_usd)::numeric, 0) AS worst_depth_usd,

    -- Sample count
    COUNT(*) AS snapshot_count

FROM liquidity_snapshots
WHERE
    DATE(timestamp) = CURRENT_DATE
GROUP BY
    symbol,
    EXTRACT(HOUR FROM timestamp)
ORDER BY
    symbol,
    hour_utc;

-- ============================================================================
-- QUERY 4: Execution Risk Score
-- ============================================================================
-- Custom risk score: combines spread, depth, and anomaly frequency
-- Score > 70 = HIGH RISK, Score < 30 = LOW RISK
-- ============================================================================

\echo '\n\n=== EXECUTION RISK SCORE (LAST 24 HOURS) ==='

WITH hourly_metrics AS (
    SELECT
        symbol,
        AVG(spread_bps) AS avg_spread,
        AVG(depth_10bps_usd) AS avg_depth,
        STDDEV(spread_bps) AS spread_volatility
    FROM liquidity_snapshots
    WHERE timestamp >= NOW() - INTERVAL '24 hours'
    GROUP BY symbol
),
anomaly_frequency AS (
    SELECT
        symbol,
        COUNT(*) AS anomaly_count_24h
    FROM anomaly_events
    WHERE detected_at >= NOW() - INTERVAL '24 hours'
    GROUP BY symbol
)
SELECT
    m.symbol,

    -- Individual components (normalized 0-100)
    ROUND(
        LEAST(100, (m.avg_spread / 10) * 100)::numeric,
        1
    ) AS spread_risk_score,

    ROUND(
        LEAST(100, (100 - (m.avg_depth / 5000)))::numeric,
        1
    ) AS depth_risk_score,

    ROUND(
        LEAST(100, COALESCE(a.anomaly_count_24h, 0) * 10)::numeric,
        1
    ) AS anomaly_risk_score,

    -- Combined risk score (weighted average)
    ROUND(
        (
            LEAST(100, (m.avg_spread / 10) * 100) * 0.3 +
            LEAST(100, (100 - (m.avg_depth / 5000))) * 0.5 +
            LEAST(100, COALESCE(a.anomaly_count_24h, 0) * 10) * 0.2
        )::numeric,
        1
    ) AS total_risk_score,

    -- Risk classification
    CASE
        WHEN (
            LEAST(100, (m.avg_spread / 10) * 100) * 0.3 +
            LEAST(100, (100 - (m.avg_depth / 5000))) * 0.5 +
            LEAST(100, COALESCE(a.anomaly_count_24h, 0) * 10) * 0.2
        ) >= 70 THEN '🔴 HIGH RISK'
        WHEN (
            LEAST(100, (m.avg_spread / 10) * 100) * 0.3 +
            LEAST(100, (100 - (m.avg_depth / 5000))) * 0.5 +
            LEAST(100, COALESCE(a.anomaly_count_24h, 0) * 10) * 0.2
        ) >= 40 THEN '🟡 MEDIUM RISK'
        ELSE '🟢 LOW RISK'
    END AS risk_level,

    -- Raw metrics
    ROUND(m.avg_spread::numeric, 2) AS avg_spread_bps,
    ROUND(m.avg_depth::numeric, 0) AS avg_depth_usd,
    COALESCE(a.anomaly_count_24h, 0) AS anomalies_24h

FROM hourly_metrics m
LEFT JOIN anomaly_frequency a ON m.symbol = a.symbol
ORDER BY total_risk_score DESC;

-- ============================================================================
-- QUERY 5: Top 10 Worst Liquidity Events
-- ============================================================================
-- Identifies the most severe liquidity crunches
-- Useful for post-trade analysis
-- ============================================================================

\echo '\n\n=== TOP 10 WORST LIQUIDITY EVENTS (LAST 7 DAYS) ==='

SELECT
    symbol,
    detected_at,
    severity,
    reason,
    max_zscore,
    ROUND(spread_bps::numeric, 2) AS spread_bps,
    ROUND(depth_10bps_usd::numeric, 0) AS depth_usd,
    ROUND(imbalance::numeric, 4) AS imbalance
FROM anomaly_events
WHERE
    detected_at >= NOW() - INTERVAL '7 days'
ORDER BY
    max_zscore DESC,
    detected_at DESC
LIMIT 10;

-- ============================================================================
-- Report Footer
-- ============================================================================

\echo '\n\n========================================='
\echo 'Report generated at:'
SELECT NOW();
\echo '========================================='
