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
SILVER_TABLE=os.getenv("SILVER_TABLE")
BRONZE_TABLE=os.getenv("BRONZE_TABLE")
Q_TABLE = "silver.hw5"

# Load Logger
os.makedirs("./pipeline/logs", exist_ok=True)

# setting up logging config
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
        logging.FileHandler("./pipeline/logs/bronze_to_silver.log"),
        logging.StreamHandler()
    ]
)

log = logging.getLogger(__name__)

# create silver schema if not exists
def startup():

    with open("./data/sql/silver_schema.sql", "r") as f:
        sql = f.read()
    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(f"SELECT COUNT(*) FROM {SILVER_TABLE};")
            count = cur.fetchone()[0]
        conn.commit()

    return count > 0

# diff new bronze entries and silver entries
def get_bronze_entries():
    
    res = pl.read_database_uri(
        query = """
            SELECT 
                b.* 
            FROM 
                bronze.hw5 b
            LEFT JOIN 
                silver.hw5 s
            ON b.symbol = s.symbol AND b.timestamp = s.timestamp
            WHERE 
                s.timestamp IS NULL
        """,
        uri=DB_URL
    )

    return res

# validate ohlc logic
def validate_ohlc(df: pl.DataFrame):

    i_mask = (
        (pl.col("high") < pl.col("low")) |
        (pl.col("high") < pl.col("open")) |
        (pl.col("high") < pl.col("close")) |
        (pl.col("low") > pl.col("open")) |
        (pl.col("low") > pl.col("close")) |
        (pl.col("volume") <= 0) |
        (pl.col("close") <= 0)
    )
    
    invalid = df.filter(i_mask)
    valid = df.filter(~i_mask)

    return valid, invalid

# data cleansing, nulls, etc.
def polish_bronze(df):

    i_mask = (
        df.is_duplicated() |
        pl.col("symbol").is_null() |
        pl.col("timestamp").is_null() |
        pl.col("open").is_null() |
        pl.col("high").is_null() |
        pl.col("low").is_null() |
        pl.col("close").is_null() |
        pl.col("volume").is_null() |
        (pl.col("open") <= 0) |
        (pl.col("close") <= 0) |
        (pl.col("high") <= 0) |
        (pl.col("low") <= 0)
    )

    invalid = df.filter(i_mask)
    valid = df.filter(~i_mask)
    
    return valid, invalid

# quarantines invalid records to silver.quarantine table
def quarantine_records(invalid_df, label):

    log.warning(f"Inserting invalid entries into silver.quarantine")

    invalid_df = invalid_df.with_columns([
        pl.lit(datetime.now(timezone.utc)).alias("quarantined_at"),
        pl.lit(label).alias("reason")
    ])

    invalid_df.write_database(
        table_name=Q_TABLE,
        connection=DB_URL,
        if_table_exists="append"
    )

# main process
if __name__ == "__main__":
    
    try:
        log.info("Starting bronze to silver pipeline.")
        startup()
        new_df = get_bronze_entries()
        log.info(f"Bronze entries detected: {len(new_df)}")

        if len(new_df) == 0:
            log.info("No new bronze entries for processing. Exiting process.")
            exit()
    
        log.info(f"Starting validation and data quality checks.")

        # OHLC
        valid_df, invalid_df = validate_ohlc(new_df)

        log.info(f"OHLC logic validations")
        log.info(f"Valid entries found: {len(valid_df)}")
        log.info(f"Invalid entries found: {len(invalid_df)}")

        if len(invalid_df) > 0:
            quarantine_records(invalid_df, "ohlc_validation")
    
        # Null and additional quality checks
        valid_df, invalid_df = polish_bronze(valid_df)
        log.info(f"Data Cleaning validations")
        log.info(f"Valid entries found: {len(valid_df)}")
        log.info(f"Invalid entries found: {len(invalid_df)}")

        if len(invalid_df) > 0:
            quarantine_records(invalid_df, "data_quality_validation")

        log.info(f"Records remaining after OHLC + Null Validations: {len(valid_df)}")


        result_df = valid_df.drop(["ingested_at", "source"]).with_columns([
            pl.lit(datetime.now(timezone.utc)).alias("processed_at")
        ])

        # write only valid columns to the silver db in append mode
        log.info(f"Writing records to silver.")

        result_df.write_database(
            table_name=SILVER_TABLE,
            connection=DB_URL,
            if_table_exists="append"
        )

        log.info(f"Silver Process Finished.")
        
    except Exception as e:
        log.error(f"Silver pipeline failed: {e}", exc_info=True)
        raise
