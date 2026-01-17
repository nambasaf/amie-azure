import logging
import azure.functions as func
from function_app import app
import sys
import pathlib
import os

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
    request_id = msg.get_body().decode("utf-8")
    logging.info(f"[IDCA QUEUE] received request_id={request_id}")

    # Lazy import AFTER sys.path fix
    from backend.idca.idca import run_idca, init_storage_clients

    storage = os.getenv("AzureWebJobsStorage")
    if not storage:
        raise RuntimeError("AzureWebJobsStorage is not set")

    init_storage_clients(storage)
    run_idca(request_id)
