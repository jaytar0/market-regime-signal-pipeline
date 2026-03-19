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

    with open("./data/sql/bronze_schema.sql", "r") as f:
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
                s.timestamp=NULL
        """,
        uri=DB_URL
    )

    return res

# validate ohlc logic
def validate_ohlc(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    invalid_mask = (
        (pl.col("high") < pl.col("low")) |
        (pl.col("high") < pl.col("open")) |
        (pl.col("high") < pl.col("close")) |
        (pl.col("low") > pl.col("open")) |
        (pl.col("low") > pl.col("close")) |
        (pl.col("volume") <= 0) |
        (pl.col("close") <= 0)
    )
    
    invalid = df.filter(invalid_mask)
    valid = df.filter(~invalid_mask)
    
    log.info(f"OHLC logic validations")
    log.info(f"Valid entries found: {len(valid)}")
    log.info(f"Invalid entries found: {len(invalid)}")

    return valid, invalid



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


    except Exception as e:
        log.error(f"Pipeline failed: {e}", exc_info=True)
        raise
