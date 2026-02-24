import azure.functions as func
import logging
import os
import datetime
import json
import re
import io
import asyncio
import sys, pathlib

from naa_test import run_steps_8_to_12
from rm_retrieval import download_and_store_rms
from rm_assessment import assess_all_rms
from prior_art_open import search_prior_art
from dataclasses import asdict

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# === SHARED CONSTANTS ===
INGESTION_CONTAINER = "manuscript-uploads"
INGESTION_TABLE = "IngestionRequests"


# === LAZY STORAGE CLIENT HELPER ===
def get_storage_clients():
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv(
        "AzureWebJobsStorage"
    )
    if not conn_str:
        raise ValueError(
            "Missing storage connection string (AZURE_STORAGE_CONNECTION_STRING or AzureWebJobsStorage)"
        )

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

        ing_table.update_entity(
            {"PartitionKey": "AMIE", "RowKey": request_id, "status": "analyzing"},
            mode="merge",
        )

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
@app.route(route="worker/run/{request_id}", methods=["POST"])
async def run_novelty_analysis(req: func.HttpRequest) -> func.HttpResponse:
    """Full NAA pipeline (Steps 8–17) implemented via naa_brain_MVP modules."""
    request_id = req.route_params.get("request_id")

    try:
        # ------------------------------------------------------------------
        # 0. Fetch ingestion record and verify state
        # ------------------------------------------------------------------
        from azure.data.tables import TableClient
        from azure.core import MatchConditions
        from datetime import datetime

        blob_service, container_client, table_service = get_storage_clients()
        ing_table = table_service.get_table_client(INGESTION_TABLE)
        
        # Idempotency check & job claiming
        table_client = TableClient.from_connection_string(
            os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage"), 
            INGESTION_TABLE
        )
        
        try:
            entity = table_client.get_entity(partition_key="AMIE", row_key=request_id)
            status = entity.get("status", "").lower()
            
            # If already processing or done, skip
            if status != "classified":
                logging.info(f"NAA cannot run from state '{status}'. Skipping.")
                return func.HttpResponse(
                    f"NAA cannot run from state '{status}'.",
                    status_code=200
                )

            # Claim the job (with optimistic concurrency)
            entity["status"] = "analyzing"
            entity["naa_started_at"] = datetime.utcnow().isoformat()
            
            table_client.update_entity(
                entity, 
                mode='replace', 
                etag=entity.metadata.get('etag'),
                match_condition=MatchConditions.IfNotModified
            )
            logging.info(f"Successfully claimed NAA job for {request_id}")

        except Exception as claim_err:
            if "ConditionNotMet" in str(claim_err) or "UpdateConditionNotSatisfied" in str(claim_err):
                logging.info(
                    f"Race condition: NAA Request {request_id} was recently claimed. Skipping."
                )
                return func.HttpResponse(
                    f"Request {request_id} already claimed.", status_code=200
                )

            logging.error(
                f"Error checking/claiming NAA job for {request_id}: {claim_err}"
            )
            return func.HttpResponse(
                "Failed to fetch or claim ingestion record.",
                status_code=500
            )          

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
        stored_blob_names = []
        try:
            stored_blob_names = await download_and_store_rms(
                request_id, naa_outputs.lor, blob_service
            )
        except Exception as e:
            logging.warning(f"RM retrieval failed: {e}")

        # ------------------------------------------------------------------
        # 3. Assess RMs (Steps 14-17) — use stored_blob_names order = search order (best first)
        # ------------------------------------------------------------------
        assessments = None
        try:
            if naa_outputs.lor:
                assessments = await assess_all_rms(
                    request_id,
                    blob_service,
                    naa_outputs.ssr,
                    naa_outputs.ss_synopsis,
                    ordered_blob_names=stored_blob_names,
                )
        except Exception as e:
            logging.warning(f"RM assessment failed: {e}")

        # ------------------------------------------------------------------
        # 4. Assemble NAA output JSON
        # ------------------------------------------------------------------
        
        # [NEW] Filter 'lor' to only include items that were successfully assessed
        # We assume stored_blob_names order matches naa_outputs.lor order (since both come from download_and_store_rms/asyncio.gather)
        filtered_lor = []
        if assessments and stored_blob_names:
            assessed_filenames = {a.filename for a in assessments}
            
            # stored_blob_names[i] corresponds to naa_outputs.lor[i]
            # We iterate through them in parallel
            if len(stored_blob_names) == len(naa_outputs.lor):
                 for i, ref in enumerate(naa_outputs.lor):
                     blob_name = stored_blob_names[i]
                     if blob_name in assessed_filenames:
                         filtered_lor.append(ref)
            else:
                logging.warning(f"Length mismatch: {len(stored_blob_names)} blobs vs {len(naa_outputs.lor)} refs. Skipping strict filtering.")
                filtered_lor = naa_outputs.lor # Fallback to everything

        naa_output_json = {
            "ss_synopsis": naa_outputs.ss_synopsis,
            "ucs": naa_outputs.ucs,
            "ss": asdict(naa_outputs.ss),
            "ssr": asdict(naa_outputs.ssr),
            "lor": filtered_lor if filtered_lor else naa_outputs.lor,
            "source_citation": idca_output.get("source_citation", "Unknown"), # <--- PRESERVED FROM IDCA
        }
        if assessments:
            naa_output_json["assessments"] = [a.__dict__ for a in assessments]

        # ------------------------------------------------------------------
        # 5. Persist NAA results (Table Storage: max 32K chars per property — use blob if larger)
        # ------------------------------------------------------------------
        naa_output_str = json.dumps(naa_output_json)
        max_table_chars = 32 * 1024 - 256  # Azure limit 32K chars; leave margin

        if len(naa_output_str) > max_table_chars:
            blob_path = f"naa-outputs/{request_id}.json"
            blob_client = container_client.get_blob_client(blob_path)
            blob_client.upload_blob(naa_output_str.encode("utf-8"), overwrite=True)
            patch = {
                "PartitionKey": "AMIE",
                "RowKey": request_id,
                "status": "assessed",
                "naa_output_blob": blob_path,
            }
            logging.info(f"NAA output stored in blob ({len(naa_output_str)} chars): {blob_path}")
        else:
            patch = {
                "PartitionKey": "AMIE",
                "RowKey": request_id,
                "status": "assessed",
                "naa_output": naa_output_str,
            }
        ing_table.update_entity(patch, mode="merge")
        logging.info(f"NAA completed for {request_id}, triggering Aggregation Agent...")

        # ------------------------------------------------------------------
        # 6. Call AA function app (SSOW Steps 18-19)
        # ------------------------------------------------------------------
        try:
            import httpx

            aa_base = os.getenv("AA_BASE", "https://aa-func-habphsfdg5ejgtcy.westus2-01.azurewebsites.net/").rstrip("/")
            key = os.getenv("AA_FUNCTION_KEY", "")
            url = f"{aa_base}/api/aa/run/{request_id}"
            if key:
                url = f"{url}?code={key}"
            r = httpx.post(url, timeout=120.0)
            r.raise_for_status()
            logging.info(f"Aggregation Agent completed for {request_id}")
        except Exception as aa_error:
            logging.error(f"Aggregation Agent failed for {request_id}: {aa_error}")
            # Still mark as assessed even if AA fails (merge so we don't re-send large props)
            ing_table.update_entity(
                {
                    "PartitionKey": "AMIE",
                    "RowKey": request_id,
                    "status": "assessed",
                    "aa_error": str(aa_error),
                },
                mode="merge",
            )

        return func.HttpResponse("NAA complete; AA triggered", status_code=200)
    # --- end of function ---

    except Exception as exc:
        logging.error(f"NAA pipeline failed: {exc}")
        try:
            _, _, table_service = get_storage_clients()
            ing_table = table_service.get_table_client(INGESTION_TABLE)
            ing_table.update_entity(
                {
                    "PartitionKey": "AMIE",
                    "RowKey": request_id,
                    "status": "failed",
                    "error": str(exc)[:32000],  # table property max 32K chars
                },
                mode="merge",
            )
        except Exception:
            pass

        return func.HttpResponse(
            f"NAA pipeline failed: {exc}", status_code=500, mimetype="text/plain"
        )
