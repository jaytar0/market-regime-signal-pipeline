from datetime import datetime, timezone
from dotenv import load_dotenv
from google.cloud import bigquery
import polars as pl
import os
import logging

load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BRONZE_TABLE = f"{GCP_PROJECT_ID}.{os.getenv('GCP_BRONZE_TABLE')}"
SILVER_TABLE = f"{GCP_PROJECT_ID}.{os.getenv('GCP_SILVER_TABLE')}"
Q_TABLE = f"{GCP_PROJECT_ID}.silver.regime_quarantine"

os.makedirs("./pipeline/logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("./pipeline/logs/bronze_to_silver.log"),
        logging.StreamHandler()
    ]
)

log = logging.getLogger(__name__)
client = bigquery.Client(project=GCP_PROJECT_ID)


def startup():
    # create silver dataset if not exists
    for dataset_name in ["silver"]:
        dataset_id = f"{GCP_PROJECT_ID}.{dataset_name}"
        try:
            client.get_dataset(dataset_id)
        except Exception:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            client.create_dataset(dataset)
            log.info(f"Created {dataset_name} dataset.")


def get_bronze_entries() -> pl.DataFrame:
    query = f"""
        SELECT b.*
        FROM `{BRONZE_TABLE}` b
        LEFT JOIN `{SILVER_TABLE}` s
        ON b.symbol = s.symbol AND b.timestamp = s.timestamp
        WHERE s.timestamp IS NULL
    """
    try:
        result = client.query(query).to_dataframe()
        return pl.from_pandas(result)
    except Exception:
        # silver table doesn't exist yet, just return all bronze
        query = f"SELECT * FROM `{BRONZE_TABLE}`"
        result = client.query(query).to_dataframe()
        return pl.from_pandas(result)


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
    return df.filter(~i_mask), df.filter(i_mask)


def polish_bronze(df: pl.DataFrame):
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
    return df.filter(~i_mask), df.filter(i_mask)


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


def quarantine_records(invalid_df: pl.DataFrame, label: str):
    log.warning(f"Inserting {len(invalid_df)} invalid entries into quarantine")
    invalid_df = invalid_df.with_columns([
        pl.lit(datetime.now(timezone.utc)).alias("quarantined_at"),
        pl.lit(label).alias("reason")
    ])
    write_to_bigquery(invalid_df, Q_TABLE)


if __name__ == "__main__":
    try:
        log.info("Starting bronze to silver pipeline.")
        startup()

        new_df = get_bronze_entries()
        log.info(f"Bronze entries detected: {len(new_df)}")

        if len(new_df) == 0:
            log.info("No new bronze entries. Exiting.")
            exit()

        log.info("Starting validation and data quality checks.")

        valid_df, invalid_df = validate_ohlc(new_df)
        log.info(f"OHLC — Valid: {len(valid_df)}, Invalid: {len(invalid_df)}")
        if len(invalid_df) > 0:
            quarantine_records(invalid_df, "ohlc_validation")

        valid_df, invalid_df = polish_bronze(valid_df)
        log.info(f"Quality — Valid: {len(valid_df)}, Invalid: {len(invalid_df)}")
        if len(invalid_df) > 0:
            quarantine_records(invalid_df, "data_quality_validation")

        log.info(f"Records remaining after validations: {len(valid_df)}")

        result_df = valid_df.drop(["ingested_at", "source"]).with_columns([
            pl.lit(datetime.now(timezone.utc)).alias("processed_at")
        ])

        log.info("Writing records to silver.")
        write_to_bigquery(result_df, SILVER_TABLE)
        log.info("Silver process finished.")

    except Exception as e:
        log.error(f"Silver pipeline failed: {e}", exc_info=True)
        raise