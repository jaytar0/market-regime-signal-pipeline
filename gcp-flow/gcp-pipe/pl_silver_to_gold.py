from datetime import datetime, timezone
from dotenv import load_dotenv
from google.cloud import bigquery
import polars as pl
import os
import logging

load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
SILVER_TABLE = f"{GCP_PROJECT_ID}.{os.getenv('GCP_SILVER_TABLE')}"
GOLD_TABLE = f"{GCP_PROJECT_ID}.{os.getenv('GCP_GOLD_TABLE')}"
ROLLING_WINDOW = int(os.getenv("ROLLING_WINDOW"))

os.makedirs("./pipeline/logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("./pipeline/logs/silver_to_gold.log"),
        logging.StreamHandler()
    ]
)

log = logging.getLogger(__name__)
client = bigquery.Client(project=GCP_PROJECT_ID)


def startup():
    dataset_id = f"{GCP_PROJECT_ID}.gold"
    try:
        client.get_dataset(dataset_id)
    except Exception:
        dataset = bigquery.Dataset(dataset_id)
        dataset.location = "US"
        client.create_dataset(dataset)
        log.info("Created gold dataset.")


def get_silver_entries() -> pl.DataFrame:
    query = f"""
        SELECT *
        FROM `{SILVER_TABLE}`
        WHERE timestamp >= (
            SELECT DATETIME_SUB(
                COALESCE(MAX(timestamp), DATETIME '1900-01-01'),
                INTERVAL {ROLLING_WINDOW} DAY
            )
            FROM `{GOLD_TABLE}`
        )
    """
    try:
        return pl.from_pandas(client.query(query).to_dataframe())
    except Exception:
        # gold table doesn't exist yet, return all silver
        query = f"SELECT * FROM `{SILVER_TABLE}`"
        return pl.from_pandas(client.query(query).to_dataframe())


def feature_engineering(df: pl.DataFrame) -> pl.DataFrame:
    df = df.sort(["symbol", "timestamp"])

    df = df.with_columns(
        (pl.col("close") / pl.col("close").shift(1).over("symbol")).log().alias("log_return")
    )
    df = df.with_columns(
        ((pl.col("high") - pl.col("low")) / pl.col("close")).alias("hl_range")
    )
    df = df.with_columns(
        (pl.col("volume") / pl.col("volume").rolling_mean(window_size=ROLLING_WINDOW).over("symbol")).alias("volume_ratio"),
    )
    df = df.with_columns(
        pl.col("log_return").rolling_std(window_size=ROLLING_WINDOW).over("symbol").alias("rolling_vol")
    )
    df = df.with_columns(
        (pl.col("log_return").rolling_mean(window_size=ROLLING_WINDOW).over("symbol") /
         pl.col("log_return").rolling_std(window_size=ROLLING_WINDOW).over("symbol")
        ).alias("rolling_sharpe"),
    )

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

    df = df.with_columns(
        (pl.col("log_return_spy") - pl.col("log_return_qqq")).alias("spy_qqq_spread")
    )
    df = df.with_columns(
        (pl.col("rolling_vol_spy") - pl.col("rolling_vol_qqq")).alias("vol_spread")
    )
    df = df.with_columns(
        (pl.col("log_return_spy") / pl.col("rolling_vol_spy")).alias("spy_sharpe_ratio")
    )
    df = df.with_columns(
        pl.rolling_corr(pl.col("log_return_spy"), pl.col("log_return_qqq"), window_size=ROLLING_WINDOW).alias("spy_qqq_corr"),
        (pl.col("rolling_vol_qqq") / pl.col("rolling_vol_spy")).alias("vol_ratio"),
    )
    df = df.with_columns(
        pl.col("spy_qqq_spread").rolling_mean(window_size=ROLLING_WINDOW).alias("spread_trend")
    )
    df = df.with_columns(
        pl.col("rolling_vol").rolling_std(window_size=ROLLING_WINDOW).over("symbol").alias("vol_of_vol")
    )
    df = df.with_columns(
        (pl.col("close") / pl.col("close").rolling_mean(window_size=ROLLING_WINDOW).over("symbol") - 1).alias("price_ma_ratio")
    )
    df = df.with_columns(
        ((pl.col("close") - pl.col("open")) / pl.col("open")).alias("close_open_gap"),
    )

    return df.filter(pl.col("symbol") == "SPY")


def write_to_bigquery(df: pl.DataFrame, table_id: str):
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        autodetect=True
    )
    job = client.load_table_from_dataframe(
        df.to_pandas(),
        table_id,
        job_config=job_config
    )
    job.result()


if __name__ == "__main__":
    try:
        log.info("Starting silver to gold pipeline.")
        startup()

        new_df = get_silver_entries()
        log.info(f"Silver entries detected: {len(new_df)}")

        if len(new_df) == 0:
            log.info("No new silver entries. Exiting.")
            exit()

        log.info("Starting feature engineering.")
        result_df = feature_engineering(new_df)
        log.info("Feature engineering complete.")

        result_df = result_df.drop(["processed_at"]).with_columns([
            pl.lit(datetime.now(timezone.utc)).alias("featured_at")
        ])

        # dedup against existing gold
        try:
            existing_keys = pl.from_pandas(
                client.query(f"SELECT symbol, timestamp FROM `{GOLD_TABLE}`").to_dataframe()
            )
            to_append = result_df.join(existing_keys, on=["symbol", "timestamp"], how="anti")
        except Exception:
            # gold table doesn't exist yet
            to_append = result_df

        if to_append.is_empty():
            log.info("No new unique records to append. Exiting.")
            exit()

        log.info(f"Appending {len(to_append)} new unique records to gold.")
        write_to_bigquery(to_append, GOLD_TABLE)
        log.info("Gold process finished.")

    except Exception as e:
        log.error(f"Gold pipeline failed: {e}", exc_info=True)
        raise