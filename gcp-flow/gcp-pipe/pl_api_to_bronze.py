from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import polars as pl
from google.cloud import bigquery

import os
import logging

# load global variables
load_dotenv()
#DB_URL =  f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@localhost:5432/{os.getenv('POSTGRES_DB')}"

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
TICKERS = os.getenv("STOCK_LIST").split(",")
#TARGET_TABLE=os.getenv("BRONZE_TABLE")
GCP_BRONZE_TABLE = os.getenv("GCP_BRONZE_TABLE")
FULL_TABLE_ID = f"{GCP_PROJECT_ID}.{GCP_BRONZE_TABLE}"

# Load Logger
os.makedirs("./pipeline/logs", exist_ok=True)

# setting up logging config
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
        logging.FileHandler("./pipeline/logs/api_to_bronze.log"),
        logging.StreamHandler()
    ]
)

log = logging.getLogger(__name__)

# ensures schema is correct and tells us whether or not out table is empty
# def startup():

#     with open("./data/sql/bronze_schema.sql", "r") as f:
#         sql = f.read()
#     with psycopg2.connect(DB_URL) as conn:
#         with conn.cursor() as cur:
#             cur.execute(sql)
#             cur.execute(f"SELECT COUNT(*) FROM {TARGET_TABLE};")
#             count = cur.fetchone()[0]
#         conn.commit()

#     return count > 0
def startup() -> bool:
    client = bigquery.Client(project=GCP_PROJECT_ID)
    
    # create dataset if it doesn't exist
    dataset_id = f"{GCP_PROJECT_ID}.bronze"
    try:
        client.get_dataset(dataset_id)
    except Exception:
        dataset = bigquery.Dataset(dataset_id)
        dataset.location = "US"
        client.create_dataset(dataset)
        log.info("Created bronze dataset.")
    
    # check if table has data
    try:
        query = f"SELECT COUNT(*) as count FROM `{FULL_TABLE_ID}`"
        result = client.query(query).result()
        count = list(result)[0].count
        return count > 0
    except Exception:
        return False

# general function for stocks, takes a start and end date as well as symbol list, returns a polars df
def request_stocks(start_date: datetime, end_date: datetime, symbol_list:list[str]):

    client = StockHistoricalDataClient(
        api_key = os.getenv("ALPACA_API_KEY"),
        secret_key = os.getenv("ALPACA_SECRET_KEY")
    )

    request = StockBarsRequest(
        symbol_or_symbols=symbol_list,
        timeframe=TimeFrame.Day,
        start=start_date,
        end=end_date,
        adjustments="all"
    )

    bars = client.get_stock_bars(request)
    return pl.from_pandas(bars.df.reset_index())

    
# requesting current data usually only 1 days worth.
# def request_current():

#     stock_list = TICKERS
    
#     last_ts = pl.read_database_uri(
#         query=f"SELECT MAX(timestamp) FROM {TARGET_TABLE}",
#         uri=DB_URL
#     )["max"][0]
def request_current():
    client = bigquery.Client(project=GCP_PROJECT_ID)
    query = f"SELECT MAX(timestamp) as max_ts FROM `{FULL_TABLE_ID}`"
    result = client.query(query).result()
    last_ts = list(result)[0].max_ts

    start = last_ts + timedelta(days=1)
    end = datetime.now(timezone.utc) - timedelta(minutes=15)

    today = datetime.now(timezone.utc).date()
    
    # check just in case it is ran twice in the same day
    if last_ts.date() >= today:
        log.warning("Already up to date, skipping.")
        return None

    if start >= end:
        log.warning("No new data is available.")
        return None

    log.info(f"Pulling data in range of {start} - {end}.")

    temp_store = request_stocks(start, end, stock_list)
    
    if len(temp_store) == 0:
        log.info(f"No records were retrieved")
        return None
    else:
        return temp_store


# main process
if __name__ == "__main__":

    # try running through entire process
    try:

        log.info("Starting Alpaca API -> Bronze pipeline")
        stock_list = TICKERS
        log.info(f"Tickers Pulled: {TICKERS}")

        # if schema does not exist or table has no data request history, otherwise append most recent
        if not startup():
            log.info(f"Historical data not detected, creating bronze schema and performing initial pull.")
            log.info(f"Bulk Time Range: {datetime(2019, 1, 1)} - {datetime(2026, 1, 1)}")
            result_df = request_stocks(datetime(2019, 1, 1), datetime(2026, 1, 1), stock_list)
        else:
            log.info(f"Historical data detected, looking for new data.")
            result_df = request_current()
        

        # if the result isnt none appending to the database with metadata
        # if result_df is not None:
        #     log.info(f"New entries detected {len(result_df)}, appending to database.")

        #     result_df = result_df.with_columns([
        #         pl.lit(datetime.now(timezone.utc)).alias("ingested_at"),
        #         pl.lit("alpaca").alias("source"),
        #     ])

        #     result_df.write_database(
        #         table_name=TARGET_TABLE,
        #         connection=DB_URL,
        #         if_table_exists="append"
        #     )

        if result_df is not None:
            log.info(f"New entries detected {len(result_df)}, writing to BigQuery.")
            result_df = result_df.with_columns([
                pl.lit(datetime.now(timezone.utc)).alias("ingested_at"),
                pl.lit("alpaca").alias("source"),
            ])
            
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=True
            )
            
            client = bigquery.Client(project=GCP_PROJECT_ID)
            job = client.load_table_from_dataframe(
                result_df.to_pandas(),
                FULL_TABLE_ID,
                job_config=job_config
            )
            job.result()
            log.info("Write complete.")
        else:
            log.warning("No new entries detected, exiting process")
        
        log.info("Process completed.")

    # if any exceptions occured send error to logs
    except Exception as e:
        log.error(f"Bronze pipeline failed: {e}", exc_info=True)
        raise
