from dotenv import load_dotenv
from google.cloud import bigquery, storage
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import RobustScaler
from statsmodels.stats.outliers_influence import variance_inflation_factor
from itertools import product
import numpy as np
import pandas as pd
import pickle
import json
import os
import logging
import warnings

load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GOLD_TABLE = f"{GCP_PROJECT_ID}.{os.getenv('GCP_GOLD_TABLE')}"
GCS_BUCKET = os.getenv("GCS_BUCKET")

os.makedirs("./pipeline/logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("./pipeline/logs/training.log"),
        logging.StreamHandler()
    ]
)

log = logging.getLogger(__name__)

bq_client = bigquery.Client(project=GCP_PROJECT_ID)
gcs_client = storage.Client(project=GCP_PROJECT_ID)


def upload_to_gcs(local_path: str, blob_name: str):
    bucket = gcs_client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path)
    log.info(f"Uploaded {blob_name} to GCS.")


if __name__ == "__main__":
    
    try:
        log.info("Starting training pipeline.")

        # load gold from bigquery
        log.info("Loading gold table from BigQuery.")
        query = f"SELECT * FROM `{GOLD_TABLE}`"
        gold_df = pd.DataFrame(bq_client.query(query).to_dataframe())

        # data cleaning
        drop_default_cols = [
            'symbol', 'featured_at', 'open', 'high', 'low', 'close',
            'volume', 'trade_count', 'vwap'
        ]
        df = gold_df.drop(columns=drop_default_cols).dropna()
        log.info(f"Shape after cleaning: {df.shape}")

        # correlation cull
        def correlation_cull(df, features, threshold=0.85):
            c_matrix = df[features].corr().abs()
            c_u = c_matrix.where(
                np.triu(np.ones(c_matrix.shape), k=1).astype(bool)
            )
            drop_logic = [c for c in c_u.columns if any(c_u[c] > threshold)]
            return [f for f in features if f not in drop_logic], drop_logic

        corr_select, corr_discard = correlation_cull(df, df.columns, 0.85)
        log.info(f"Dropped by correlation: {corr_discard}")

        # vif cull
        def vif_cull(df, features, threshold=10):
            remaining = features.copy()
            while True:
                X = df[remaining].dropna()
                scaler = RobustScaler()
                X_scaled = scaler.fit_transform(X)
                vif_data = pd.DataFrame({
                    'feature': remaining,
                    'VIF': [variance_inflation_factor(X_scaled, i)
                            for i in range(X_scaled.shape[1])]
                }).sort_values('VIF', ascending=False)
                max_vif = vif_data.iloc[0]['VIF']
                max_feat = vif_data.iloc[0]['feature']
                if max_vif > threshold:
                    log.info(f"Dropping '{max_feat}' with VIF = {max_vif:.2f}")
                    remaining.remove(max_feat)
                else:
                    break
            return remaining

        corr_select.remove("timestamp")
        feature_cols_final = vif_cull(df, corr_select, threshold=10)
        log.info(f"Final features ({len(feature_cols_final)}): {feature_cols_final}")

        feature_cols_final_no_ts = [col for col in feature_cols_final if col != 'timestamp']

        # train/test split
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx]
        test_df = df.iloc[split_idx:]

        log.info(f"Train: {train_df['timestamp'].min()} to {train_df['timestamp'].max()} — {len(train_df)} rows")
        log.info(f"Test:  {test_df['timestamp'].min()} to {test_df['timestamp'].max()} — {len(test_df)} rows")

        X_train = train_df[feature_cols_final_no_ts].values
        X_test = test_df[feature_cols_final_no_ts].values

        scaler = RobustScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # grid search
        param_grid = {
            'n_components':    [3],
            'covariance_type': ['full'],
            'n_iter':          [100],
            'random_state':    [420]
        }

        keys = list(param_grid.keys())
        values = list(param_grid.values())

        best_model = None
        best_bic = float("inf")
        best_params = None

        warnings.filterwarnings('ignore')

        for combo in product(*values):
            params = dict(zip(keys, combo))

            model = GaussianHMM(
                n_components=params['n_components'],
                covariance_type=params['covariance_type'],
                n_iter=params['n_iter'],
                random_state=params['random_state']
            )

            try:
                model.fit(X_train_scaled)
            except Exception as e:
                log.warning(f"Failed: {params} | {e}")
                continue

            if not model.monitor_.converged:
                log.warning(f"Did not converge: {params}")
                continue

            # calculate BIC
            n_samples, n_features = X_train_scaled.shape
            n_states = model.n_components
            cov_type = model.covariance_type

            if cov_type == 'full':
                cov_params = n_states * n_features * (n_features + 1) / 2
            elif cov_type == 'tied':
                cov_params = n_features * (n_features + 1) / 2
            elif cov_type == 'diag':
                cov_params = n_states * n_features
            elif cov_type == 'spherical':
                cov_params = n_states

            k = (n_states**2 - n_states) + (n_states - 1) + (n_states * n_features) + cov_params
            log_lik = model.score(X_train_scaled)
            bic = -2 * log_lik + k * np.log(n_samples)

            log.info(f"BIC: {bic:.2f} | {params}")

            if bic < best_bic:
                best_bic = bic
                best_model = model
                best_params = params

        if best_model is None:
            raise RuntimeError("No converged model found.")

        log.info(f"Best model: {best_params} | BIC: {best_bic:.2f}")

        # save artifacts locally
        os.makedirs("./artifacts", exist_ok=True)

        with open("./artifacts/model.pkl", "wb") as f:
            pickle.dump(best_model, f)

        with open("./artifacts/scaler.pkl", "wb") as f:
            pickle.dump(scaler, f)

        feature_cols_clean = [col for col in feature_cols_final_no_ts
                              if col != 'hmm_n3_full_iter100_seed420_regime']

        with open("./artifacts/feature_cols.json", "w") as f:
            json.dump(feature_cols_clean, f)

        # upload to GCS
        upload_to_gcs("./artifacts/model.pkl", "model.pkl")
        upload_to_gcs("./artifacts/scaler.pkl", "scaler.pkl")
        upload_to_gcs("./artifacts/feature_cols.json", "feature_cols.json")

        log.info("Training complete. All artifacts uploaded to GCS.")

    except Exception as e:
        log.error(f"Training pipeline failed: {e}", exc_info=True)
        raise