CREATE SCHEMA IF NOT EXISTS bronze;

-- Daily bars
CREATE TABLE IF NOT EXISTS bronze.daily_bars (
    id          SERIAL PRIMARY KEY,
    symbol      VARCHAR(10) NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL,
    open        NUMERIC(12,4),
    high        NUMERIC(12,4),
    low         NUMERIC(12,4),
    close       NUMERIC(12,4),
    volume      BIGINT,
    trade_count BIGINT,
    vwap        NUMERIC(12,4),
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, timestamp)
);

-- Hourly bars
CREATE TABLE IF NOT EXISTS bronze.hourly_bars (
    id          SERIAL PRIMARY KEY,
    symbol      VARCHAR(10) NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL,
    open        NUMERIC(12,4),
    high        NUMERIC(12,4),
    low         NUMERIC(12,4),
    close       NUMERIC(12,4),
    volume      BIGINT,
    trade_count BIGINT,
    vwap        NUMERIC(12,4),
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, timestamp)
);