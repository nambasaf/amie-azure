import azure.functions as func
import logging
import os
import datetime
import json
import re
import io
from backend.naa.prior_art_open import search_prior_art

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# === SHARED CONSTANTS ===
INGESTION_CONTAINER = "manuscript-uploads"
INGESTION_TABLE = "IngestionRequests"


# === LAZY STORAGE CLIENT HELPER ===
def get_storage_clients():
    conn_str = os.getenv("AzureWebJobsStorage")
    if not conn_str:
        raise ValueError("Missing AzureWebJobsStorage connection string")

    # Import here to keep top-level light
    from azure.storage.blob import BlobServiceClient
    from azure.data.tables import TableServiceClient

    blob_service = BlobServiceClient.from_connection_string(conn_str)
    container_client = blob_service.get_container_client(INGESTION_CONTAINER)
    table_service = TableServiceClient.from_connection_string(conn_str)

    return container_client, table_service


# === TEXT EXTRACTION (PDF → TEXT) ===
def get_manuscript_text(blob_name: str) -> str:
    try:
        container_client, _ = get_storage_clients()
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

        _, table_service = get_storage_clients()
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
        _, table_service = get_storage_clients()
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
        _, table_service = get_storage_clients()
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
def run_novelty_analysis(req: func.HttpRequest) -> func.HttpResponse:
    request_id = req.route_params.get("request_id")

    try:
        container_client, table_service = get_storage_clients()
        ing_table = table_service.get_table_client(INGESTION_TABLE)
        entity = ing_table.get_entity("AMIE", request_id)

        filename = entity["filename"]
        filing_date = entity.get("filing_date", "2025-01-01")

        # === 1. GET CLAIMS FROM IDCA OUTPUT ===
        idca_output = json.loads(entity.get("idca_output", "{}"))
        claims = idca_output.get("structural_synopsis", "")

        # Fallback: extract from PDF if IDCA didn't provide
        if not claims:
            text = get_manuscript_text(filename)
            claims_match = re.search(r"1\.?\s+(.+?)(?=\n[A-Z]|$)", text, re.I)
            claims = claims_match.group(1).strip() if claims_match else ""

        if not claims:
            raise Exception("No claims found from IDCA or PDF")

        # === 2. SEARCH PRIOR ART ===
        matches = search_prior_art(claims)

        # === 3. §102: SINGLE REFERENCE ANTICIPATION ===
        blocking_ref = None
        claim_elements = [
            e.strip().lower() for e in claims.split(";") if len(e.strip()) > 10
        ]

        for ref in matches:
            pub_date = ref.get("publication_date", "1900-01-01")
            if pub_date >= filing_date:
                continue
            snippet = ref["snippet"].lower()
            if all(elem in snippet for elem in claim_elements):
                blocking_ref = ref
                break

        # === 4. FINAL RESULT ===
        is_novel = blocking_ref is None
        score = 0.95 if is_novel else 0.20
        reasoning = (
            "No single prior art reference discloses all claim elements before filing date (35 U.S.C. §102)."
            if is_novel
            else f"Anticipated by {blocking_ref['patent_id']} (published {blocking_ref.get('publication_date')})."
        )

        # === 5. SAVE TO TABLE ===
        entity.update(
            {
                "status": "assessed",
                "novelty": "novel" if is_novel else "not_novel",
                "patentability_score": score,
                "matches": json.dumps(matches),
                "reasoning": reasoning,
                "blocking_reference": json.dumps(blocking_ref) if blocking_ref else "",
                "completed_at": datetime.datetime.utcnow().isoformat(),
            }
        )
        ing_table.update_entity(entity)

        return func.HttpResponse("§102 assessment complete", status_code=200)

    except Exception as e:
        logging.error(f"NAA failed: {e}")
        try:
            _, table_service = get_storage_clients()
            ing_table = table_service.get_table_client(INGESTION_TABLE)
            entity = ing_table.get_entity("AMIE", request_id)
            entity["status"] = "failed"
            entity["error"] = str(e)
            ing_table.update_entity(entity)
        except:
            pass
        return func.HttpResponse("Analysis failed", status_code=500)
