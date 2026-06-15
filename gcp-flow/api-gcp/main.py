from fastapi import FastAPI
from google.cloud import storage
import pickle
import json
import numpy as np
import os
from contextlib import asynccontextmanager

model = None
scaler = None
feature_cols = None

REGIME_LABELS = {
    2: "Crisis",
    1: "Bull/Calm",
    0: "Transitional"
}

GCS_BUCKET = os.getenv("GCS_BUCKET", "indicator-model")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")


def download_from_gcs(blob_name: str, local_path: str):
    client = storage.Client(project=GCP_PROJECT_ID)
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(local_path)
    print(f"Downloaded {blob_name} from GCS.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model, scaler, feature_cols

    download_from_gcs("model.pkl", "/tmp/model.pkl")
    download_from_gcs("scaler.pkl", "/tmp/scaler.pkl")
    download_from_gcs("feature_cols.json", "/tmp/feature_cols.json")

    with open("/tmp/model.pkl", "rb") as f:
        model = pickle.load(f)

    with open("/tmp/scaler.pkl", "rb") as f:
        scaler = pickle.load(f)

    with open("/tmp/feature_cols.json", "r") as f:
        feature_cols = json.load(f)

    print("Model, scaler, and feature cols loaded successfully.")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/regime")
def predict_regime(features: dict):
    try:
        x = np.array([[features[col] for col in feature_cols]])
        x_scaled = scaler.transform(x)
        regime = int(model.predict(x_scaled)[0])
        return {
            "regime": regime,
            "label": REGIME_LABELS.get(regime, "Unknown")
        }
    except KeyError as e:
        return {"error": f"Missing feature: {e}"}


@app.get("/regime/cols")
def get_cols():
    return {"feature_columns": feature_cols}