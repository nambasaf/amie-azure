"""
Queue-trigger function that launches IDCA then NAA

Queue name: idca-queue
Message body: plain request-id string
"""
from __future__ import annotations

import os
import subprocess
import pathlib
import logging
import httpx
import azure.functions as func

# IMPORTANT: attach to the SAME Function App
from function_app import app

# Resolve project root so Python can import the backend package
ROOT = pathlib.Path(__file__).resolve().parents[2]

STORAGE = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
PYTHON = os.getenv("IDCA_PYTHON", "python")

# Base URL for the NAA Function
# Corrected to 7073 as per start_services.ps1
NAA_BASE = os.getenv("NAA_BASE", "http://localhost:7073/api")


def _run_idca(request_id: str):
    """Executes backend.idca.idca synchronously for the request-id."""
    cmd = [
        PYTHON,
        "-m",
        "backend.idca.idca",
        "--request-id",
        request_id,
        "--storage",
        STORAGE,
    ]
    logging.info("Starting IDCA for %s", request_id)
    # Use capture_output=True and check=True to see errors in logs
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True
    )
    logging.info("IDCA stdout: %s", result.stdout)
    logging.info("IDCA finished for %s", request_id)


@app.queue_trigger(
    arg_name="msg",
    queue_name="idca-queue",
    connection="AZURE_STORAGE_CONNECTION_STRING",
)
def idca_queue(msg: func.QueueMessage):
    request_id = msg.get_body().decode("utf-8")

    if not request_id:
        logging.warning("Received empty message in idca-queue")
        return

    try:
        _run_idca(request_id)
    except Exception as e:
        logging.exception("IDCA run failed: %s", e)
        return

    # IDCA itself will now trigger NAA if an invention is detected.
    # We no longer need to trigger it here to avoid double-calls.
    pass
