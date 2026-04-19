CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.regime (

    -- default vals
    symbol              TEXT NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    open                DOUBLE PRECISION,
    high                DOUBLE PRECISION,
    low                 DOUBLE PRECISION,
    close               DOUBLE PRECISION,
    volume              DOUBLE PRECISION,
    trade_count         DOUBLE PRECISION,
    vwap                DOUBLE PRECISION,

    -- per symbol calculations
    log_return          DOUBLE PRECISION,
    hl_range            DOUBLE PRECISION,
    volume_ratio        DOUBLE PRECISION,
    rolling_vol         DOUBLE PRECISION,
    rolling_sharpe      DOUBLE PRECISION,

    -- feature engineering
    log_return_spy      DOUBLE PRECISION,
    hl_range_spy        DOUBLE PRECISION,
    volume_ratio_spy    DOUBLE PRECISION,
    rolling_vol_spy     DOUBLE PRECISION,
    rolling_sharpe_spy  DOUBLE PRECISION,
    log_return_qqq      DOUBLE PRECISION,
    hl_range_qqq        DOUBLE PRECISION,
    volume_ratio_qqq    DOUBLE PRECISION,
    rolling_vol_qqq     DOUBLE PRECISION,
    rolling_sharpe_qqq  DOUBLE PRECISION,
    spy_qqq_spread      DOUBLE PRECISION,
    vol_spread          DOUBLE PRECISION,
    spy_sharpe_ratio    DOUBLE PRECISION,
    spy_qqq_corr        DOUBLE PRECISION,
    vol_ratio           DOUBLE PRECISION,
    spread_trend        DOUBLE PRECISION,
    vol_of_vol          DOUBLE PRECISION,
    price_ma_ratio      DOUBLE PRECISION,
    close_open_gap      DOUBLE PRECISION,
    featured_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, timestamp)
);