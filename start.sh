#!/bin/bash
docker compose up -d
#mlflow ui --backend-store-uri sqlite:///data/mlflow/mlflow.db > data/mlflow/mlflow.log 2>&1 &
echo "Postgres and MLflow running"

#mlflow ui --backend-store-uri sqlite:///data/mlflow/mlflow.db