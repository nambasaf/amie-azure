import logging
import os
import sys
import pathlib

import httpx
import azure.functions as func
from function_app import app

# Ensure backend/ is importable
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@app.function_name(name="idca_queue_worker")
@app.queue_trigger(
    arg_name="msg",
    queue_name="idca-queue",
    connection="AzureWebJobsStorage",
)
def idca_queue_worker(msg: func.QueueMessage):
    """
    Runs in the ingestion app when a message lands on idca-queue.
    Does NOT run IDCA here — only POSTs to the standalone IDCA function app (e.g. port 7072).
    """
    request_id = msg.get_body().decode("utf-8")
    logging.info(f"[IDCA QUEUE] received request_id={request_id} (will trigger standalone IDCA app)")

    # Call the IDCA function app; IDCA runs in that app, not in this process
    idca_base = os.getenv("IDCA_BASE", "https://idca-func-hbergrcufpbmh2e5.westus2-01.azurewebsites.net/").rstrip("/")
    key = os.getenv("IDCA_FUNCTION_KEY", "")
    url = f"{idca_base}/idca/run/{request_id}"
    if key:
        url = f"{url}?code={key}"
    try:
        r = httpx.post(url, timeout=30.0)
        r.raise_for_status()
        logging.info(
            f"[IDCA QUEUE] triggered IDCA app for {request_id}: {r.status_code}"
        )
    except Exception as e:
        logging.error(f"[IDCA QUEUE] failed to trigger IDCA app for {request_id}: {e}")
        raise
