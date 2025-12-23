"""Queue-trigger function that launches IDCA then NAA

Queue name: idca-queue
Message body: plain request-id string

Steps:
1. Run backend.idca.idca for the request-id (updates status to 'classified').
2. Immediately trigger the existing NAA HTTP Function so the pipeline
   continues automatically.
"""
from __future__ import annotations

import os
import subprocess
import pathlib
import logging
import azure.functions as func
import httpx

# Resolve project root so Python can import the backend package
ROOT = pathlib.Path(__file__).resolve().parents[2]

STORAGE = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
PYTHON = os.getenv("IDCA_PYTHON", "python")

# Base URL for the NAA Function (worker endpoint)
NAA_BASE = os.getenv("NAA_BASE", "http://localhost:7071/api")


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
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    logging.info("IDCA finished for %s", request_id)


def main(msg: func.QueueMessage):  # noqa: D401
    request_id = msg.get_body().decode()
    if not request_id:
        logging.warning("Received empty message in idca-queue")
        return

    try:
        _run_idca(request_id)
    except Exception as e:  # pragma: no cover
        logging.exception("IDCA run failed: %s", e)
        return

    # Trigger NAA HTTP Function
    try:
        r = httpx.post(f"{NAA_BASE}/worker/run/{request_id}", timeout=5.0)
        logging.info("Triggered NAA for %s – status %s", request_id, r.status_code)
    except Exception as e:
        logging.warning("Failed to trigger NAA: %s", e)

