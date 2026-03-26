from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import polars as pl
import psycopg2
import os
import logging

# load global variables
load_dotenv()
DB_URL =  f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@localhost:5432/{os.getenv('POSTGRES_DB')}"
GOLD_TABLE=os.getenv("GOLD_TABLE")
SILVER_TABLE=os.getenv("SILVER_TABLE")
ROLLING_WINDOW=int(os.getenv("ROLLING_WINDOW"))
#Load Logger
os.makedirs("./pipeline/logs", exist_ok=True)

# setting up logging config
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
        logging.FileHandler("./pipeline/logs/silver_to_gold.log"),
        logging.StreamHandler()
    ]
)

log = logging.getLogger(__name__)

# create silver schema if not exists
def startup():

    with open("./data/sql/gold_schema.sql", "r") as f:
        sql = f.read()
    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(f"SELECT COUNT(*) FROM {GOLD_TABLE};")
            count = cur.fetchone()[0]
        conn.commit()

    return count > 0



# get new silver entries that are not in gold
def get_silver_entries():

    res = pl.read_database_uri(
        query="""
        SELECT * 
        FROM silver.regime 
        WHERE timestamp >= (
            SELECT COALESCE(MAX(timestamp), '1900-01-01'::timestamp) - INTERVAL '20 days' 
            FROM gold.regime
        )
        """,
        uri=DB_URL
    )

    return res


# calculate all new fields
def feature_engineering(df):
     
    df = df.sort(["symbol", "timestamp"])
    
    # log return
    # additive returns over time that are normally distributed.
    df = df.with_columns(
        (pl.col("close") / pl.col("close").shift(1).over("symbol")).log().alias("log_return")
    )

    # hl range (high low spread)
    # this is also known as intraday range, the thought is the wider the range the more the uncertainty.
    df = df.with_columns(
        ((pl.col("high") - pl.col("low")) / pl.col("close")).alias("hl_range")
    )

    # volume ratio
    # volume over rolling average. raw volume by itself not very useful. Tells you whether or not
    # the participation in the stock is abnormally high or low relative to its own norm.
    df = df.with_columns(
        (pl.col("volume") / pl.col("volume").rolling_mean(window_size=ROLLING_WINDOW).over("symbol")).alias("volume_ratio"),
    )
    
    # rolling volume
    # rolling  standard deviation of log returns. A fundamental indicator for quants, low volume
    # behaves differently than high volume and this is an indicator to capture that behavior
    df = df.with_columns(
        pl.col("log_return").rolling_std(window_size=ROLLING_WINDOW).over("symbol").alias("rolling_vol")
    )

    # rolling sharpe
    # mean return dvided by rolling standard deviation. Used to distinguish between low volume (good sharpe)
    # or zero to negative sharpe that indicates quality of return.
    df = df.with_columns(
        (pl.col("log_return").rolling_mean(window_size=ROLLING_WINDOW).over("symbol") /
         pl.col("log_return").rolling_std(window_size=ROLLING_WINDOW).over("symbol")
        ).alias("rolling_sharpe"),
    )
    
    # Pull out individual features and join them on a wide form
    parsed_spy = df.filter(pl.col("symbol") == "SPY").select([
        "timestamp",
        pl.col("log_return").alias("log_return_spy"),
        pl.col("hl_range").alias("hl_range_spy"),
        pl.col("volume_ratio").alias("volume_ratio_spy"),
        pl.col("rolling_vol").alias("rolling_vol_spy"),
        pl.col("rolling_sharpe").alias("rolling_sharpe_spy"),
    ])
    
    parsed_qqq = df.filter(pl.col("symbol") == "QQQ").select([
        "timestamp",
        pl.col("log_return").alias("log_return_qqq"),
        pl.col("hl_range").alias("hl_range_qqq"),
        pl.col("volume_ratio").alias("volume_ratio_qqq"),
        pl.col("rolling_vol").alias("rolling_vol_qqq"),
        pl.col("rolling_sharpe").alias("rolling_sharpe_qqq"),
    ])
    
    df = df.join(parsed_spy, on="timestamp", how="left")
    df = df.join(parsed_qqq, on="timestamp", how="left")
    
    # calculated metrics between both

    # spy - qqq spread
    # this can tell us the risk signal. When tech leads QQQ this is negative spread and it means
    # people want to be more risky for growth, and the opposite is true for conservatism
    df = df.with_columns(
        (pl.col("log_return_spy") - pl.col("log_return_qqq")).alias("spy_qqq_spread")
    )

    # rolling volume spread
    # Difference in volatility of spy and qqq. this calculates how disproportionate each are from each other
    # used as early indicator because you will see a larger negative given by QQQ *tech movements effect the market
    df = df.with_columns(
        (pl.col("rolling_vol_spy") - pl.col("rolling_vol_qqq")).alias("vol_spread")
    )

    # spy sharpe ratio
    # a simple grounder for whether the market is in a rewarding or chaotic phase. When the sharpe is bad it means individual
    # stocks all move together.
    df = df.with_columns(
        (pl.col("log_return_spy") / pl.col("rolling_vol_spy")).alias("spy_sharpe_ratio")
    )

    # spy + qqq correlation
    # just tracks whether or not spy or qqq is moving similarly. when it diverges it usually means a regime is changing
    # because money is moving between sectors.
    df = df.with_columns(
        pl.rolling_corr(pl.col("log_return_spy"), pl.col("log_return_qqq"), window_size=ROLLING_WINDOW).alias("spy_qqq_corr"),
        (pl.col("rolling_vol_qqq") / pl.col("rolling_vol_spy")).alias("vol_ratio"),
    )
    
    # spread trend
    # tells us whether one or the other is beating each other consistently. If there is a sustained trend it may
    # signal a regime change
    df = df.with_columns(
        pl.col("spy_qqq_spread").rolling_mean(window_size=ROLLING_WINDOW).alias("spread_trend")
    )

    # vol_of_vol
    # tells us how consistently volatile a market is, steady vs erratic
    df = df.with_columns(
        pl.col("rolling_vol").rolling_std(window_size=ROLLING_WINDOW).over("symbol").alias("vol_of_vol")
    )
    
    # this is basically rolling mean reversion is it coming back to its mean or is it consistently above or below average
    df = df.with_columns(
        (pl.col("close") / pl.col("close").rolling_mean(window_size=ROLLING_WINDOW).over("symbol") - 1).alias("price_ma_ratio")
    )

    # it just means did the stock go up or down today during the trading day. tells you more so the overall price action.
    df = df.with_columns(
        ((pl.col("close") - pl.col("open")) / pl.col("open")).alias("close_open_gap"),
    )

    return df.filter(pl.col("symbol") == "SPY")

# main process
if __name__ == "__main__":
    
    try:
        log.info("Starting silver to gold pipeline.")
        startup()
        new_df = get_silver_entries()
        log.info(f"Silver entries detected: {len(new_df)}")

        if len(new_df) == 0:
            log.info("No new silver entries for processing. Exiting process.")
            exit()
    
        log.info(f"Starting feature engineering.")
        
        result_df = feature_engineering(new_df)

        log.info(f"Finished writing new features.")

        result_df = result_df.drop(["processed_at"]).with_columns([
            pl.lit(datetime.now(timezone.utc)).alias("featured_at")
        ])

        log.info(f"Try writing records to gold.")

        existing_gold_keys = pl.read_database_uri(
            query=f"SELECT symbol, timestamp FROM {GOLD_TABLE}",
            uri=DB_URL
        )

        to_append = result_df.join(
            existing_gold_keys, 
            on=["symbol", "timestamp"], 
            how="anti"
        )      

        if to_append.is_empty():
            log.info("No new unique records to append. Exiting.")
            exit()

        log.info(f"Appending {len(to_append)} new unique records to gold.")

        to_append.write_database(
            table_name=GOLD_TABLE,
            connection=DB_URL,
            if_table_exists="append" 
        )

        log.info(f"Gold Process Finished.")

    except Exception as e:
        log.error(f"Gold pipeline failed: {e}", exc_info=True)
        raise 
