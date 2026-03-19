CREATE SCHEMA IF NOT EXISTS gold;


-- hw 5 usage only
CREATE TABLE IF NOT EXISTS gold.hw5 (
    symbol          TEXT                NOT NULL,
    timestamp       TIMESTAMPTZ         NOT NULL,
    open            DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    close           DOUBLE PRECISION,
    volume          DOUBLE PRECISION,
    trade_count     DOUBLE PRECISION,
    vwap            DOUBLE PRECISION,
    log_return      DOUBLE PRECISION,
    hl_range        DOUBLE PRECISION,
    volume_ratio    DOUBLE PRECISION,
    rolling_vol     DOUBLE PRECISION,
    rolling_sharpe  DOUBLE PRECISION,
    featured_at     TIMESTAMPTZ         NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, timestamp)
);