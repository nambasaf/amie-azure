import azure.functions as func
import logging
import json
import os
import uuid
import datetime
import mimetypes
import posixpath
import re

from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient
from azure.storage.queue import QueueClient, TextBase64EncodePolicy

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

CONTAINER_NAME = "manuscript-uploads"
TABLE_NAME = "IngestionRequests"
QUEUE_NAME = "idca-queue"
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}

# Config from Environment
STORAGE_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")


def _get_table_client():
    if not STORAGE_CONN_STR:
        raise RuntimeError("Storage connection string not configured.")
    service = TableServiceClient.from_connection_string(STORAGE_CONN_STR)
    service.create_table_if_not_exists(TABLE_NAME)
    return service.get_table_client(TABLE_NAME)


def _get_blob_service():
    if not STORAGE_CONN_STR:
        raise RuntimeError("Storage connection string not configured.")
    return BlobServiceClient.from_connection_string(STORAGE_CONN_STR)


def _get_container_client():
    container_client = _get_blob_service().get_container_client(CONTAINER_NAME)
    if not container_client.exists():
        container_client.create_container()
    return container_client


def _get_queue_client():
    if not STORAGE_CONN_STR:
        raise RuntimeError("Storage connection string not configured.")
    queue_client = QueueClient.from_connection_string(
        STORAGE_CONN_STR,
        queue_name=QUEUE_NAME,
        message_encode_policy=TextBase64EncodePolicy(),
    )
    try:
        queue_client.create_queue()
    except Exception:
        pass
    return queue_client


def json_rpc_error(code: int, message: str, req_id: str = None) -> func.HttpResponse:
    payload = {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
        "id": req_id,
    }
    return func.HttpResponse(
        json.dumps(payload), mimetype="application/json", status_code=200
    )


def json_rpc_success(result: dict, req_id: str) -> func.HttpResponse:
    payload = {
        "jsonrpc": "2.0",
        "result": result,
        "id": req_id,
    }
    return func.HttpResponse(
        json.dumps(payload), mimetype="application/json", status_code=200
    )


def _sanitize_filename(filename: str | None) -> str:
    name = (filename or "manuscript.pdf").strip()
    name = name.split("/")[-1].split("\\")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if not name:
        name = "manuscript.pdf"
    return name[:128]


def _normalize_extension(filename: str, mime_type: str | None = None) -> str:
    ext = posixpath.splitext(filename)[1].lower()
    if ext in ALLOWED_EXTENSIONS:
        return ext

    guessed = mimetypes.guess_extension(mime_type or "")
    if guessed == ".ksh":
        guessed = ".txt"
    if guessed in ALLOWED_EXTENSIONS:
        return guessed
    return ".pdf"


def _guess_content_type(filename: str, mime_type: str | None = None) -> str:
    if mime_type in ALLOWED_CONTENT_TYPES:
        return mime_type
    guessed, _ = mimetypes.guess_type(filename)
    if guessed in ALLOWED_CONTENT_TYPES:
        return guessed
    return "application/pdf"


def _build_final_blob_name(request_id: str, filename: str, mime_type: str | None = None) -> str:
    safe_name = _sanitize_filename(filename)
    ext = _normalize_extension(safe_name, mime_type)
    return f"{request_id}{ext}"


def _load_json_if_possible(value):
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _load_blob_text(container_client, blob_name: str | None):
    if not blob_name:
        return None
    try:
        data = container_client.get_blob_client(blob_name).download_blob().readall()
        text = data.decode("utf-8")
        return _load_json_if_possible(text)
    except Exception as exc:
        logging.warning(f"Could not load blob payload '{blob_name}': {exc}")
        return None


def _normalize_status(raw_status: str) -> str:
    raw = (raw_status or "unknown").lower()
    if raw in ["uploaded", "queued"]:
        return "queued"
    if raw in ["classifying", "classified", "analyzing", "assessed"]:
        return "running"
    if raw == "completed":
        return "completed"
    if raw == "failed":
        return "failed"
    return "unknown"


def _build_result_payload(entity: dict) -> dict:
    result = {
        "request_id": entity.get("RowKey"),
        "status": entity.get("status", "unknown"),
        "normalized_status": _normalize_status(entity.get("status", "unknown")),
        "filename": entity.get("filename"),
        "uploaded_at": entity.get("uploaded_at"),
        "completed_at": entity.get("completed_at"),
    }

    raw_status = (entity.get("status") or "").lower()
    if raw_status in ["assessed", "completed", "failed"]:
        container_client = _get_container_client()
        result["idca_output"] = _load_json_if_possible(entity.get("idca_output"))
        result["naa_output"] = _load_json_if_possible(entity.get("naa_output"))
        result["aa_output"] = entity.get("aa_output")

        if result["naa_output"] is None:
            result["naa_output"] = _load_blob_text(
                container_client, entity.get("naa_output_blob")
            )
        if result["aa_output"] is None:
            result["aa_output"] = _load_blob_text(
                container_client, entity.get("aa_output_blob")
            )
            
        # Explicitly map the final AA output to a 'report' field for downstream agents
        result["report"] = result["aa_output"]
        
        if entity.get("error"):
            result["error"] = entity.get("error")

    return result


@app.route(route="agent-card.json", methods=["GET"])
def get_agent_card(req: func.HttpRequest) -> func.HttpResponse:
    """Returns the A2A Agent Card."""
    card = {
        "name": "amie-agent",
        "description": "Analyzes private manuscripts for invention disclosure, prior art, and final assessment. Manuscripts are uploaded directly as binary via the HTTP endpoint.",
        "protocol": "json-rpc-2.0",
        "version": "1.0",
        "endpoint": "/api/a2a",
        "capabilities": [
            {
                "name": "upload_manuscript",
                "type": "http-upload",
                "endpoint": "/api/upload",
                "method": "POST",
                "description": "Uploads a manuscript binary directly to the AMIE agent for analysis",
                "headers": {
                    "Content-Type": "application/octet-stream",
                    "x-file-name": "string"
                }
            },
            "invention_detection",
            "novelty_assessment",
            "report_generation"
        ],  
        "methods": [
            {
                "name": "get_status",
                "description": "Check the status of a manuscript analysis.",
                "parameters": {"request_id": "string"},
            },
        ],
    }
    return func.HttpResponse(json.dumps(card), mimetype="application/json", status_code=200)


def _handle_get_status(params: dict, rpc_id: str) -> func.HttpResponse:
    request_id = params.get("request_id")
    if not request_id:
        return json_rpc_error(-32602, "Missing parameter 'request_id'", rpc_id)

    try:
        table_client = _get_table_client()
        entity = table_client.get_entity(partition_key="AMIE", row_key=request_id)
    except Exception:
        return json_rpc_error(
            -32602, f"Request ID '{request_id}' not found.", rpc_id
        )

    result = _build_result_payload(entity)
    return json_rpc_success(result, rpc_id)


@app.route(route="a2a", methods=["POST"])
def a2a_rpc(req: func.HttpRequest) -> func.HttpResponse:
    """The main JSON-RPC 2.0 endpoint."""
    try:
        body = req.get_json()
    except ValueError:
        return json_rpc_error(-32700, "Parse error: Invalid JSON")

    if body.get("jsonrpc") != "2.0":
        return json_rpc_error(-32600, "Invalid Request: 'jsonrpc' must be '2.0'")

    method = body.get("method")
    if not method:
        return json_rpc_error(-32600, "Invalid Request: missing 'method'")

    rpc_id = body.get("id")
    params = body.get("params", {})
    if not isinstance(params, dict):
        return json_rpc_error(-32602, "Invalid params: expected an object", rpc_id)

    if method == "get_status":
        return _handle_get_status(params, rpc_id)
    return json_rpc_error(-32601, f"Method '{method}' not found", rpc_id)

@app.route(route="upload", methods=["POST"])
def upload_manuscript(req: func.HttpRequest) -> func.HttpResponse:
    # Read binary bytes
    file_bytes = req.get_body()
    
    # 2. Add validation for file size
    if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
        return func.HttpResponse(
            "File exceeds maximum allowed size", 
            status_code=400
        )

    if not file_bytes:
        return func.HttpResponse("No file uploaded", status_code=400)

    # Obtain requested filename from header
    raw_filename = req.headers.get("x-file-name", "manuscript.pdf")
    mime_type = req.headers.get("Content-Type", "application/octet-stream")

    request_id = str(uuid.uuid4())
    filename = _sanitize_filename(raw_filename)

    # Retain final blob naming logic
    blob_name = _build_final_blob_name(request_id, filename, mime_type)

    try:
        container = _get_container_client()
        blob_client = container.get_blob_client(blob_name)
        blob_client.upload_blob(file_bytes, overwrite=True)
    except Exception as exc:
        logging.error(f"Failed to upload blob for {request_id}: {exc}")
        return func.HttpResponse("Failed to upload manuscript to storage", status_code=500)

    try:
        table_client = _get_table_client()
        entity = {
            "PartitionKey": "AMIE",
            "RowKey": request_id,
            "filename": blob_name,
            "status": "queued",
            "uploaded_at": datetime.datetime.utcnow().isoformat(),
            "a2a_original_filename": raw_filename,
            "a2a_blob_path": blob_name,
            "a2a_content_type": mime_type,
            "a2a_size_bytes": len(file_bytes),
            "analysis_started_at": None,
            "pipeline_version": "1.0",
        }
        table_client.create_entity(entity)
    except Exception as exc:
        logging.error(f"Failed to create table entity for {request_id}: {exc}")
        return func.HttpResponse("Failed to create tracking record", status_code=500)

    try:
        _get_queue_client().send_message(request_id)
    except Exception as exc:
        logging.error(f"Failed to trigger pipeline queue for {request_id}: {exc}")
        return func.HttpResponse("Failed to trigger analysis pipeline", status_code=500)

    return func.HttpResponse(
        json.dumps({
            "request_id": request_id,
            "status": "queued"
        }),
        mimetype="application/json",
        status_code=202
    )


