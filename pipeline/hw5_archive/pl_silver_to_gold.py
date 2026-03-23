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
            SELECT 
                s.* 
            FROM 
                silver.hw5 s
            LEFT JOIN 
                gold.hw5 g
            ON s.symbol = g.symbol AND s.timestamp = g.timestamp
            WHERE 
                g.timestamp IS NULL
        """,
        uri=DB_URL
    )

    return res


# calculate all new fields
def feature_engineering(df):
    
    # sort by symbol and timestamp first
    df = df.sort(["symbol", "timestamp"])
    
    # log return
    df = df.with_columns(
        (pl.col("close") / pl.col("close").shift(1).over("symbol")).log().alias("log_return")
    )
    
    # high-low range
    df = df.with_columns(
        ((pl.col("high") - pl.col("low")) / pl.col("close")).alias("hl_range")
    )
    
    # volume ratio
    df = df.with_columns(
        (pl.col("volume") / pl.col("volume").rolling_mean(window_size=ROLLING_WINDOW).over("symbol")).alias("volume_ratio")
    )
    
    # rolling volatility 
    df = df.with_columns(
        pl.col("log_return").rolling_std(window_size=ROLLING_WINDOW).over("symbol").alias("rolling_vol")
    )
    
    # rolling sharpe
    df = df.with_columns(
        (   
            pl.col("log_return").rolling_mean(window_size=ROLLING_WINDOW).over("symbol") /
            pl.col("log_return").rolling_std(window_size=ROLLING_WINDOW).over("symbol")
        ).alias("rolling_sharpe")
    )
    
    return df


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

        log.info(f"Finished writing new features, sending records to gold: {len(result_df)}")

        result_df = result_df.drop(["processed_at"]).with_columns([
            pl.lit(datetime.now(timezone.utc)).alias("featured_at")
        ])

        log.info(f"Writing records to gold.")

        result_df.write_database(
            table_name=GOLD_TABLE,
            connection=DB_URL,
            if_table_exists="append"
        )

        log.info(f"Gold Process Finished.")

    except Exception as e:
        log.error(f"Gold pipeline failed: {e}", exc_info=True)
        raise 
