"""IDCA Runner Azure Function

POST /idca/run/{request_id}
--------------------------
Fire-and-forget wrapper that launches the existing CLI implementation
(`python -m backend.idca.idca`) in a background subprocess so the caller
returns immediately (202 Accepted).  This keeps the heavy LLM call out of
the HTTP request latency budget and re-uses all the logic already built
into `backend/idca/idca.py`.

Environment variables expected (same as ingestion agent):
    AZURE_STORAGE_CONNECTION_STRING  – full connection string for Table & Blob
    IDCA_PYTHON                       – optional, explicit python executable
"""

from __future__ import annotations

import os
import sys
import subprocess
import pathlib
import logging
import azure.functions as func

# Ensure project root is on path so `backend` package is importable
ROOT = (
    pathlib.Path(__file__).resolve().parents[2]
)  # <repo>/backend/idca_func/function_app.py
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# Config
STORAGE = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv(
    "AzureWebJobsStorage"
)
PYTHON = os.getenv("IDCA_PYTHON", sys.executable)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="idca/run/{request_id}", methods=["POST", "GET"])
def run_idca(req: func.HttpRequest) -> func.HttpResponse:  # noqa: D401
    """Kick off IDCA for the given request-id in a background process."""
    request_id = req.route_params.get("request_id")
    if not request_id:
        return func.HttpResponse("Missing request_id", status_code=400)

    if not STORAGE:
        return func.HttpResponse(
            "Storage connection string not configured", status_code=500
        )

    # Build command: python -m backend.idca.idca --request-id <id> --storage <conn>
    cmd = [
        PYTHON,
        "-m",
        "backend.idca.idca",
        "--request-id",
        request_id,
        "--storage",
        STORAGE,
    ]

    # Launch without waiting (fire-and-forget)
    # But capture output to a log file so we can debug
    try:
        log_file = ROOT / "idca_logs" / f"idca_{request_id}.log"
        log_file.parent.mkdir(exist_ok=True)

        with open(log_file, "w") as log:
            process = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        logging.info(
            f"IDCA subprocess started for {request_id} (PID: {process.pid}, log: {log_file})"
        )
    except Exception as e:
        logging.error(f"Failed to start IDCA subprocess: {e}", exc_info=True)
        return func.HttpResponse(f"Failed to start IDCA: {e}", status_code=500)

    return func.HttpResponse(
        f"IDCA started for {request_id}", status_code=202, mimetype="text/plain"
    )
