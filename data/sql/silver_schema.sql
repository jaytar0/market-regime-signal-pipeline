CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE IF NOT EXISTS silver.regime (
    symbol        TEXT        NOT NULL,
    timestamp     TIMESTAMPTZ NOT NULL,
    open          DOUBLE PRECISION,
    high          DOUBLE PRECISION,
    low           DOUBLE PRECISION,
    close         DOUBLE PRECISION,
    volume        DOUBLE PRECISION,
    trade_count   DOUBLE PRECISION,
    vwap          DOUBLE PRECISION,
    processed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, timestamp)
);


CREATE TABLE IF NOT EXISTS silver.regime_quarantine (
    symbol          TEXT,
    timestamp       TIMESTAMPTZ,
    open            DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    close           DOUBLE PRECISION,
    volume          DOUBLE PRECISION,
    trade_count     DOUBLE PRECISION,
    vwap            DOUBLE PRECISION,
    ingested_at     TIMESTAMPTZ,
    source          TEXT,
    quarantined_at  TIMESTAMPTZ,
    reason          TEXT
);
