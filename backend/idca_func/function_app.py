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
import pathlib
import logging
import importlib
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


@app.route(route="idca/run/{request_id}", methods=["POST"])
def run_idca(req: func.HttpRequest) -> func.HttpResponse:  # noqa: D401
    """Kick off IDCA for the given request-id in a background process."""
    request_id = req.route_params.get("request_id")
    logging.info(f"[IDCA WRAPPER] Received request for request_id={request_id}")
    if not request_id:
        return func.HttpResponse("Missing request_id", status_code=400)

    if not STORAGE:
        logging.error("[IDCA WRAPPER] Storage connection string not configured")
        return func.HttpResponse(
            "Storage connection string not configured", status_code=500
        )
    logging.info("[IDCA WRAPPER] Storage configuration present")

    required_runtime_envs = [
        "PROJECT_ENDPOINT",
        "MODEL_DEPLOYMENT",
        "IDCA_AGENT_ID",
        "DOC_INTELLIGENCE_ENDPOINT",
        "DOC_INTELLIGENCE_KEY",
    ]
    missing_envs = [name for name in required_runtime_envs if not os.getenv(name)]
    if missing_envs:
        msg = f"Missing required IDCA environment variable(s): {', '.join(missing_envs)}"
        logging.error(f"[IDCA WRAPPER] {msg}")
        return func.HttpResponse(msg, status_code=500)

    # Directly import and run the IDCA agent
    # This ensures the Azure Function stays alive until the job is done
    try:
        from azure.data.tables import TableClient
        from datetime import datetime

        logging.info("[IDCA WRAPPER] Importing idca.run_idca")
        idca_module = importlib.import_module("idca")
        idca_runner = getattr(idca_module, "run_idca")
        logging.info("[IDCA WRAPPER] Import run_idca succeeded")

        table_client = TableClient.from_connection_string(STORAGE, "IngestionRequests")
        logging.info("[IDCA WRAPPER] TableClient initialized")
        
        # 1. Idempotency Check & Job Claiming
        try:
            entity = table_client.get_entity(partition_key="AMIE", row_key=request_id)
            status = entity.get("status", "").lower()
            logging.info(f"[IDCA WRAPPER] Table entity fetched. current_status='{status}'")
            
            # If already processing or done, skip
            if status in ["classifying", "classified", "completed", "assessed", "analyzing", "failed"]:
                logging.info(f"Request {request_id} is already in state '{status}'. Skipping duplicate trigger.")
                return func.HttpResponse(f"Request {request_id} already being processed or completed.", status_code=200)

            # 2. Claim the job (with optimistic concurrency)
            from azure.core import MatchConditions
            entity["status"] = "classifying"
            entity["classifying_started_at"] = datetime.utcnow().isoformat()
            metadata = getattr(entity, "metadata", {}) or {}
            etag = metadata.get("etag")

            # Use the ETag when available to ensure no one else claimed it since we read it
            if etag:
                table_client.update_entity(
                    entity,
                    mode="replace",
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified
                )
                logging.info(f"[IDCA WRAPPER] Successfully claimed IDCA job with ETag for {request_id}")
            else:
                logging.warning(
                    f"[IDCA WRAPPER] No ETag available on entity for {request_id}; "
                    "falling back to replace update without optimistic concurrency"
                )
                table_client.update_entity(entity, mode="replace")
                logging.info(f"[IDCA WRAPPER] Successfully claimed IDCA job without ETag for {request_id}")

        except Exception as claim_err:
            # If ETag mismatch, someone else probably grabbed it
            if "ConditionNotMet" in str(claim_err) or "UpdateConditionNotSatisfied" in str(claim_err):
                logging.info(f"Race condition: Request {request_id} was recently claimed by another process. Skipping.")
                return func.HttpResponse(f"Request {request_id} already claimed.", status_code=200)
            
            logging.error(f"[IDCA WRAPPER] Error checking/claiming job for {request_id}: {claim_err}", exc_info=True)
            return func.HttpResponse(f"Failed to claim IDCA job: {claim_err}", status_code=500)

        logging.info(f"[IDCA WRAPPER] Starting IDCA logic directly for {request_id}")
        idca_runner(request_id, preclaimed=True)
        logging.info(f"[IDCA WRAPPER] IDCA logic completed for {request_id}")
    except Exception as e:
        logging.error(f"[IDCA WRAPPER] IDCA logic failed for {request_id}: {e}", exc_info=True)
        return func.HttpResponse(f"Failed to run IDCA: {type(e).__name__}: {e}", status_code=500)

    return func.HttpResponse(
        f"IDCA started for {request_id}", status_code=202, mimetype="text/plain"
    )
