FROM python:3.11-slim
WORKDIR /app
RUN pip install polars pandas google-cloud-bigquery google-cloud-storage alpaca-py python-dotenv pyarrow statsmodels hmmlearn scikit-learn db-dtypes
COPY . .
CMD ["python", "gcp_cloudrunner_hmm.py"]