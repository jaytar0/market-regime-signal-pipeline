from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime
import os
from dotenv import load_dotenv
import polars as pl
from sqlalchemy import create_engine, text

load_dotenv()

client = StockHistoricalDataClient(
    api_key=os.getenv("ALPACA_API_KEY"),
    secret_key=os.getenv("ALPACA_SECRET_KEY")
)

def request_history(client):
    request = StockBarsRequest(
        symbol_or_symbols=["AMZN", "XLK"],
        timeframe=TimeFrame.Day,
        start=datetime(2019, 1, 1),
        end=datetime(2026, 1, 1),
        adjustments="all"
    )

    bars = client.get_stock_bars(request)
    df = bars.df.reset_index()
    df = pl.from_pandas(df)
    print(df.columns)
    print(df)

    # connect and commit
    query = ""

def request_current(client):

    request = StockBarsRequest(
        symbol_or_symbols=["AMZN", "XLK"],
        timeframe=TimeFrame.Day,
        start=datetime(2019, 1, 1),
        end=datetime(2026, 1, 1),
        adjustments="all"
    )

    bars = client.get_stock_bars(request)

    # connect and commit

def active_db(client):

    # connect and check status
    NotImplemented

def table_log(client):

    # function that logs a new entry to the run logs table for observability
    NotImplemented

if not active_db(client):
    result_df = request_history(client)
else:
    result_df = request_current(client)

# step down here to add metadata
# add ingested_at, updated_at, source, adjustment

# make sure all data is in thereOHLCV + vwap + trade_count 


# execute query

# write to table logs

