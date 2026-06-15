from dotenv import load_dotenv
from google.cloud import bigquery
import requests
import os
import subprocess

load_dotenv()

url = os.getenv("REGIME_ENDPOINT")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")

client = bigquery.Client(project=GCP_PROJECT_ID)

# get token from gcloud
token = subprocess.check_output(
    ["gcloud.cmd", "auth", "print-identity-token"],
    shell=True
).decode().strip()

headers = {"Authorization": f"Bearer {token}"}

# get latest gold row
query = f"""
    SELECT * FROM `{GCP_PROJECT_ID}.gold.regime`
    ORDER BY timestamp DESC
    LIMIT 1
"""

result = client.query(query).to_dataframe()
latest = result.iloc[0]
print(latest['timestamp'])

# get feature cols
cols_response = requests.get(f"{url}/regime/cols", headers=headers)
print(cols_response.status_code)
feature_cols = cols_response.json()["feature_columns"]

# build feature dict
features = {col: float(latest[col]) for col in feature_cols}

# hit regime endpoint
response = requests.post(f"{url}/regime", json=features, headers=headers)
print(response.json())