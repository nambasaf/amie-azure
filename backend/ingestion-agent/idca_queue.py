import logging
import os
import sys
import pathlib

import azure.functions as func
from azure.data.tables import TableClient
from function_app import app

# Ensure backend/ is importable
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _update_ingestion_status(request_id: str, status: str, **extra_fields) -> None:
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
    if not conn_str:
        logging.error(
            f"[IDCA QUEUE] Cannot update status for {request_id}: missing storage connection string"
        )
        return

    try:
        table_client = TableClient.from_connection_string(conn_str, "IngestionRequests")
        patch = {
            "PartitionKey": "AMIE",
            "RowKey": request_id,
            "status": status,
        }
        patch.update(extra_fields)
        table_client.update_entity(entity=patch, mode="merge")
    except Exception as exc:
        logging.error(f"[IDCA QUEUE] Failed to update status for {request_id}: {exc}")


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
    idca_base = os.getenv("IDCA_BASE", "https://idca-func-hbergrcufpbmh2e5.westus2-01.azurewebsites.net").rstrip("/")
    key = os.getenv("IDCA_FUNCTION_KEY", "")
    url = f"{idca_base}/api/idca/run/{request_id}"
    if key:
        url = f"{url}?code={key}"
    else:
        logging.warning(
            f"[IDCA QUEUE] IDCA_FUNCTION_KEY is empty for request {request_id}. "
            "If IDCA uses AuthLevel.FUNCTION, the hosted callback will fail."
        )
    try:
        import httpx

        # Increased timeout to 10 minutes to allow IDCA's LLM run to finish without retrying
        r = httpx.post(url, timeout=600.0)
        if r.status_code >= 400:
            body = (r.text or "")[:500]
            logging.error(
                f"[IDCA QUEUE] IDCA trigger failed for {request_id}: "
                f"status={r.status_code}, url={url}, body={body}"
            )
            _update_ingestion_status(
                request_id,
                "idca_trigger_failed",
                idca_error=f"HTTP {r.status_code}",
                idca_trigger_url=url,
            )
            if r.status_code in {401, 403, 404}:
                return
            r.raise_for_status()

        logging.info(
            f"[IDCA QUEUE] triggered IDCA app for {request_id}: {r.status_code}"
        )
    except Exception as e:
        logging.error(f"[IDCA QUEUE] failed to trigger IDCA app for {request_id}: {e}")
        _update_ingestion_status(
            request_id,
            "idca_trigger_failed",
            idca_error=str(e),
            idca_trigger_url=url,
        )
        raise
