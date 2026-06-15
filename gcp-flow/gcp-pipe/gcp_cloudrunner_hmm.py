import subprocess
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()]
)

log = logging.getLogger(__name__)

scripts = [
    "pl_api_to_bronze.py",
    "pl_bronze_to_silver.py",
    "pl_silver_to_gold.py",
]

for script in scripts:
    log.info(f"Running {script}")
    result = subprocess.run(
        [sys.executable, script],
        check=True
    )
    log.info(f"Finished {script}")

log.info("Pipeline complete.")