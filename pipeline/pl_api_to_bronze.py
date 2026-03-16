from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

client = StockHistoricalDataClient(
    api_key=os.getenv("ALPACA_API_KEY"),
    secret_key=os.getenv("ALPACA_SECRET_KEY")
)

request = StockBarsRequest(
    symbol_or_symbols=["SPY", "QQQ"],
    timeframe=TimeFrame.Day,
    start=datetime(2020, 1, 1),
    end=datetime(2024, 1, 1)
)

bars = client.get_stock_bars(request)
df = bars.df

print(df.head(20))
print(f"\nShape: {df.shape}")
print(f"\nSymbols: {df.index.get_level_values('symbol').unique().tolist()}")