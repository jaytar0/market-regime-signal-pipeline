CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.regime (
    symbol        TEXT        NOT NULL,
    timestamp     TIMESTAMPTZ NOT NULL,
    open          DOUBLE PRECISION,
    high          DOUBLE PRECISION,
    low           DOUBLE PRECISION,
    close         DOUBLE PRECISION,
    volume        DOUBLE PRECISION,
    trade_count   DOUBLE PRECISION,
    vwap          DOUBLE PRECISION,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    source        TEXT,
    PRIMARY KEY (symbol, timestamp)
);
