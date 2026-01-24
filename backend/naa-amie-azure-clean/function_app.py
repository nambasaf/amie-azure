import azure.functions as func
import logging
import os
import datetime
import json
import re
import io
import asyncio
import sys, pathlib

# Ensure repository root is on path for backend.aa and backend.naa_brain_MVP imports
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]  # Go up to repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.naa_brain_MVP.naa_test import run_steps_8_to_12
from backend.naa_brain_MVP.rm_retrieval import download_and_store_rms
from backend.naa_brain_MVP.rm_assessment import assess_all_rms
from prior_art_open import search_prior_art

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# === SHARED CONSTANTS ===
INGESTION_CONTAINER = "manuscript-uploads"
INGESTION_TABLE = "IngestionRequests"


# === LAZY STORAGE CLIENT HELPER ===
def get_storage_clients():
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
    if not conn_str:
        raise ValueError("Missing storage connection string (AZURE_STORAGE_CONNECTION_STRING or AzureWebJobsStorage)")

    # Import here to keep top-level light
    from azure.storage.blob import BlobServiceClient
    from azure.data.tables import TableServiceClient

    blob_service = BlobServiceClient.from_connection_string(conn_str)
    container_client = blob_service.get_container_client(INGESTION_CONTAINER)
    table_service = TableServiceClient.from_connection_string(conn_str)

    return blob_service, container_client, table_service


# === TEXT EXTRACTION (PDF → TEXT) ===
def get_manuscript_text(blob_name: str) -> str:
    try:
        _, container_client, _ = get_storage_clients()
        blob_client = container_client.get_blob_client(blob_name)
        data = blob_client.download_blob().readall()

        if not blob_name.lower().endswith(".pdf"):
            return ""

        from pypdf import PdfReader  # Lazy import

        reader = PdfReader(io.BytesIO(data))
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + " "
        return text.strip()
    except Exception as e:
        logging.error(f"Text extraction failed: {e}")
        return ""


# === POST /assess — START NAA ===
@app.route(route="assess", methods=["POST"])
def start_assessment(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
        request_id = body.get("request_id")
        if not request_id:
            return func.HttpResponse("Missing request_id", status_code=400)

        _, _, table_service = get_storage_clients()
        ing_table = table_service.get_table_client(INGESTION_TABLE)

        try:
            entity = ing_table.get_entity("AMIE", request_id)
        except:
            return func.HttpResponse("Request not found", status_code=404)

        if entity.get("status") != "classified":
            return func.HttpResponse("IDCA must complete first", status_code=400)

        entity["status"] = "analyzing"
        ing_table.update_entity(entity)

        return func.HttpResponse(
            json.dumps({"request_id": request_id, "message": "NAA started"}),
            mimetype="application/json",
            status_code=202,
        )
    except Exception as e:
        logging.error(f"NAA start failed: {e}")
        return func.HttpResponse("Server error", status_code=500)


# === GET /assess/{request_id} — FULL RESULT ===
@app.route(route="assess/{request_id}", methods=["GET"])
def get_assessment(req: func.HttpRequest) -> func.HttpResponse:
    request_id = req.route_params.get("request_id")

    try:
        _, _, table_service = get_storage_clients()
        ing_table = table_service.get_table_client(INGESTION_TABLE)
        entity = ing_table.get_entity("AMIE", request_id)

        return func.HttpResponse(
            json.dumps(
                {
                    "request_id": request_id,
                    "status": entity.get("status", "unknown"),
                    "novelty": entity.get("novelty"),
                    "patentability_score": entity.get("patentability_score"),
                    "matches": json.loads(entity.get("matches", "[]")),
                    "reasoning": entity.get("reasoning", ""),
                    "blocking_reference": json.loads(
                        entity.get("blocking_reference", "null") or "null"
                    ),
                    "completed_at": entity.get("completed_at"),
                },
                indent=2,
            ),
            mimetype="application/json",
        )
    except:
        return func.HttpResponse("Not found", status_code=404)


# === GET /assess/{request_id}/status ===
@app.route(route="assess/{request_id}/status", methods=["GET"])
def get_status(req: func.HttpRequest) -> func.HttpResponse:
    request_id = req.route_params.get("request_id")

    try:
        _, _, table_service = get_storage_clients()
        ing_table = table_service.get_table_client(INGESTION_TABLE)
        entity = ing_table.get_entity("AMIE", request_id)

        return func.HttpResponse(
            json.dumps({"request_id": request_id, "status": entity.get("status")}),
            mimetype="application/json",
        )
    except:
        return func.HttpResponse("Not found", status_code=404)


# === POST /worker/run/{request_id} — RUN §102 ANALYSIS ===
# === POST /worker/run/{request_id} — RUN §102 ANALYSIS ===
@app.route(route="worker/run/{request_id}", methods=["POST"])
async def run_novelty_analysis(req: func.HttpRequest) -> func.HttpResponse:
    """Full NAA pipeline (Steps 8–17) implemented via naa_brain_MVP modules."""
    request_id = req.route_params.get("request_id")

    try:
        # ------------------------------------------------------------------
        # 0. Fetch ingestion record and verify state
        # ------------------------------------------------------------------
        blob_service, container_client, table_service = get_storage_clients()
        ing_table = table_service.get_table_client(INGESTION_TABLE)
        entity = ing_table.get_entity("AMIE", request_id)
        if entity.get("status") not in ("classified", "analyzing"):
            return func.HttpResponse("IDCA not completed", status_code=400)

        # Set status to analyzing at start
        entity["status"] = "analyzing"
        ing_table.update_entity(entity)

        filename = entity["filename"]
        idca_output = json.loads(entity.get("idca_output", "{}"))

        # ------------------------------------------------------------------
        # 1. Run full NAA pipeline (Steps 8-12)
        # ------------------------------------------------------------------
        manuscript_text = get_manuscript_text(filename)
        # Fix: Await the async pipeline
        naa_outputs = await run_steps_8_to_12(manuscript_text, idca_output)

        # ------------------------------------------------------------------
        # 2. Retrieve Reference Manuscripts (Step 13)
        # ------------------------------------------------------------------
        try:
            # Fix: Await directly
            await download_and_store_rms(request_id, naa_outputs.lor, blob_service)
        except Exception as e:
            logging.warning(f"RM retrieval failed: {e}")

        # ------------------------------------------------------------------
        # 3. Assess RMs (Steps 14-17)
        # ------------------------------------------------------------------
        assessments = None
        try:
            if naa_outputs.lor:
                # Fix: Await directly
                assessments = await assess_all_rms(
                    request_id,
                    blob_service,
                    naa_outputs.ssr,
                    naa_outputs.ss_synopsis,
                )
        except Exception as e:
            logging.warning(f"RM assessment failed: {e}")

        # ------------------------------------------------------------------
        # 4. Assemble NAA output JSON
        # ------------------------------------------------------------------
        
        source_citation = idca_output.get("source_citation", "Unknown Citation")

        naa_output_json = {
            "ss_synopsis": naa_outputs.ss_synopsis,
            "source_citation": source_citation,
            "assessments": []
        }

        if assessments:
            for a in assessments:
                naa_output_json["assessments"].append(
                    {
                        "reference_citation": a.reference_citation,
                        "rs_synopsis": a.rs_synopsis,
                        "scores": {
                            "css": a.sos_score.get("css", 0),
                            "ewss": a.sos_score.get("ewss", 0),
                        },
                        "status_determination": a.status_determination,
                    }
                )

        # ------------------------------------------------------------------
        # 5. Persist NAA results to Table Storage
        # ------------------------------------------------------------------
        entity.update(
            {
                "status": "naa_completed",  # Mark as ready for AA
                "naa_output": json.dumps(naa_output_json),
            }
        )
        ing_table.update_entity(entity)
        logging.info(f"NAA completed for {request_id}, triggering Aggregation Agent...")

        # ------------------------------------------------------------------
        # 6. Trigger Aggregation Agent (via HTTP)
        # ------------------------------------------------------------------
        try:
            import httpx
            
            # Use environment variable for AA URL, default to local port 7074
            aa_base_url = os.getenv("AA_SERVICE_URL", "http://localhost:7074/api")
            aa_url = f"{aa_base_url}/aa/run/{request_id}"
            
            logging.info(f"[TRIGGER] Posting to AA Service at {aa_url}")
            
            # Fire and forget (or wait for confirmation of trigger, but AA is long running)
            # Since AA is a function app, we generally want to wait for the response to know it started?
            # actually AA runs synchronously in its function, so we might want to wait or use a durable pattern.
            # For now, we await the POST response to ensure it started successfully.
            async with httpx.AsyncClient(timeout=300.0) as client:
                 resp = await client.post(aa_url)
                 resp.raise_for_status()

            logging.info(f"[TRIGGER] Aggregation Agent triggered successfully for {request_id}")

        except Exception as aa_error:
            logging.error(f"Failed to trigger Aggregation Agent for {request_id}: {aa_error}")
            # We do NOT mark as completed. It stays as 'naa_completed' (or 'assessed').
            # We could mark as failed_aa_trigger if we want.
            entity = ing_table.get_entity("AMIE", request_id)
            entity["aa_error"] = f"Trigger Failed: {str(aa_error)}"
            ing_table.update_entity(entity)

        return func.HttpResponse("NAA completed, AA triggered", status_code=200)
    # --- end of function ---

    except Exception as exc:
        logging.error(f"NAA pipeline failed: {exc}")
        try:
            _, _, table_service = get_storage_clients()
            ing_table = table_service.get_table_client(INGESTION_TABLE)
            entity = ing_table.get_entity("AMIE", request_id)
            entity["status"] = "failed"
            entity["error"] = str(exc)
            ing_table.update_entity(entity)
        except Exception:
            pass

        return func.HttpResponse(
            f"NAA pipeline failed: {exc}", status_code=500, mimetype="text/plain"
        )
