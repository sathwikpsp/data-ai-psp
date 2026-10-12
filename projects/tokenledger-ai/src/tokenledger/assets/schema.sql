CREATE TABLE IF NOT EXISTS rate_cards (
    version VARCHAR PRIMARY KEY, document VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS ingestion_batches (
    batch_id VARCHAR PRIMARY KEY, created_at TIMESTAMPTZ DEFAULT current_timestamp,
    source VARCHAR NOT NULL, accepted INTEGER, duplicates INTEGER, rejected INTEGER
);
CREATE TABLE IF NOT EXISTS bronze_events (
    request_id VARCHAR PRIMARY KEY, batch_id VARCHAR NOT NULL,
    payload_hash VARCHAR NOT NULL, record_json VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_events (
    request_id VARCHAR PRIMARY KEY, event_time TIMESTAMPTZ NOT NULL,
    provider VARCHAR NOT NULL, model VARCHAR NOT NULL, team VARCHAR NOT NULL,
    environment VARCHAR NOT NULL, input_tokens BIGINT NOT NULL,
    output_tokens BIGINT NOT NULL, cached_input_tokens BIGINT NOT NULL,
    latency_ms DOUBLE NOT NULL, status VARCHAR NOT NULL,
    cost_microusd BIGINT NOT NULL CHECK (cost_microusd >= 0),
    rate_card_version VARCHAR NOT NULL, batch_id VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_issues (
    batch_id VARCHAR NOT NULL, row_number INTEGER NOT NULL, reason VARCHAR NOT NULL
);
CREATE VIEW IF NOT EXISTS daily_usage AS
SELECT CAST(event_time AT TIME ZONE 'UTC' AS DATE) AS day, team,
    SUM(cost_microusd)::BIGINT AS cost_microusd,
    COUNT(*)::INTEGER AS requests,
    SUM(input_tokens)::BIGINT AS input_tokens,
    SUM(output_tokens)::BIGINT AS output_tokens,
    SUM(cached_input_tokens)::BIGINT AS cached_input_tokens,
    AVG(latency_ms) AS latency_ms,
    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END)::INTEGER AS errors
FROM usage_events GROUP BY day, team;
