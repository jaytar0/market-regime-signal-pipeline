from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
import polars as pl
from sqlalchemy import create_engine, text
import psycopg2

# load global variables
load_dotenv()
DB_URL =  f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@localhost:5432/{os.getenv('POSTGRES_DB')}"
TICKERS = os.getenv("STOCK_LIST").split(",")

# ensures schema is correct and tells us whether or not out table is empty
def startup():

    with open("./data/sql/bronze_schema.sql", "r") as f:
        sql = f.read()
    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute("SELECT COUNT(*) FROM bronze.hw5;")
            count = cur.fetchone()[0]
        conn.commit()

    return count > 0


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
def request_current():

    stock_list = TICKERS
    
    last_ts = pl.read_database_uri(
        query="SELECT MAX(timestamp) FROM bronze.hw5",
        uri=DB_URL
    )["max"][0]

    start = last_ts + timedelta(days=1)
    end = datetime.now(timezone.utc)

    today = datetime.now(timezone.utc).date()
    
    # check just in case it is ran twice in the same day
    if last_ts.date() >= today:
        print("Already up to date, skipping.")
        return None

    if start >= end:
        print("No new data is available.")
        return None
    
    return request_stocks(start, end, stock_list)


# function that logs a new entry to the run logs table for observability
def table_log(client):

    NotImplemented


if __name__ == "__main__":

    stock_list = TICKERS
    # if schema does not exist or table has no data request history, otherwise append most recent
    if not startup():
        result_df = request_stocks(datetime(2019, 1, 1), datetime(2026, 1, 1), stock_list)
    else:
        result_df = request_current()
    
    if result_df is not None:

        result_df.write_database(
            table_name="bronze.hw5",
            connection=DB_URL,
            if_table_exists="append"
        )
# step down here to add metadata
# add ingested_at, updated_at, source, adjustment

# make sure all data is in thereOHLCV + vwap + trade_count 


# execute query

# write to table logs

