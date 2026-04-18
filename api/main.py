from fastapi import FastAPI
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

MODEL_PATH = "/mlflow/mlruns/3/075ebf7057c34bcfa6c94c13b0fb02eb/artifacts/hmm_n3_full_iter100_seed420"

@asynccontextmanager
async def lifespan(app: FastAPI):
    global model, scaler, feature_cols

    with open("model.pkl", "rb") as f:
        model = pickle.load(f)

    with open("scaler.pkl", "rb") as f:
        scaler = pickle.load(f)

    with open("feature_cols.json", "r") as f:
        feature_cols = json.load(f)

    print("Model, scaler, and feature cols loaded successfully")
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