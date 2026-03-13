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
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import generate_blob_sas, BlobSasPermissions
from datetime import timedelta

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

CONTAINER_NAME = "manuscript-uploads"
TABLE_NAME = "IngestionRequests"
QUEUE_NAME = "idca-queue"
STAGING_PREFIX = "a2a-staging"
DEFAULT_UPLOAD_TTL_MINUTES = 15
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
    except ResourceExistsError:
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


def _build_staging_blob_name(request_id: str, filename: str) -> str:
    safe_name = _sanitize_filename(filename)
    return f"{STAGING_PREFIX}/{request_id}/{safe_name}"


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
        if entity.get("error"):
            result["error"] = entity.get("error")

    return result


@app.route(route="agent-card.json", methods=["GET"])
def get_agent_card(req: func.HttpRequest) -> func.HttpResponse:
    """Returns the A2A Agent Card."""
    card = {
        "name": "amie-agent",
        "description": "Analyzes private manuscripts for invention disclosure, prior art, and final assessment. Manuscripts are uploaded privately to signed blob URLs and then processed asynchronously.",
        "protocol": "json-rpc-2.0",
        "version": "1.0",
        "endpoint": "/api/a2a",
        "capabilities": [
            "manuscript_upload",
            "invention_detection",
            "novelty_assessment",
            "report_generation"
        ],  
        "methods": [
            {
                "name": "get_upload_url",
                "description": "Request a short-lived signed upload URL for a private manuscript.",
                "parameters": {
                    "filename": "string (Optional: original file name. Defaults to manuscript.pdf)",
                    "mime_type": "string (Optional: content type such as application/pdf)",
                    "size_bytes": "number (Optional: expected file size in bytes)",
                    "sha256": "string (Optional: checksum for client-side integrity)",
                    "client_request_id": "string (Optional: caller correlation ID)",
                },
            },
            {
                "name": "submit_manuscript",
                "description": "Finalize a previously uploaded manuscript and enqueue the AMIE pipeline.",
                "parameters": {
                    "request_id": "string (Required: ID returned from get_upload_url)",
                    "filename": "string (Optional: original file name if different from the initial request)",
                    "mime_type": "string (Optional: content type to validate)",
                    "size_bytes": "number (Optional: expected blob size)",
                    "sha256": "string (Optional: checksum supplied by caller)",
                },
            },
            {
                "name": "get_status",
                "description": "Check the status of a manuscript analysis.",
                "parameters": {"request_id": "string"},
            },
        ],
    }
    return func.HttpResponse(json.dumps(card), mimetype="application/json", status_code=200)


def _handle_get_upload_url(params: dict, rpc_id: str) -> func.HttpResponse:
    request_id = str(uuid.uuid4())
    requested_filename = _sanitize_filename(params.get("filename"))
    mime_type = _guess_content_type(requested_filename, params.get("mime_type"))
    size_bytes = params.get("size_bytes")
    if size_bytes is not None and int(size_bytes) > MAX_UPLOAD_SIZE_BYTES:
        return json_rpc_error(
            -32602,
            f"Requested file size exceeds limit of {MAX_UPLOAD_SIZE_BYTES} bytes.",
            rpc_id,
        )

    blob_name = _build_staging_blob_name(request_id, requested_filename)
    _get_container_client()

    blob_service = _get_blob_service()
    account_name = blob_service.account_name
    account_key = blob_service.credential.account_key
    expires_at = datetime.datetime.utcnow() + timedelta(
        minutes=DEFAULT_UPLOAD_TTL_MINUTES
    )

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=CONTAINER_NAME,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(create=True, write=True),
        expiry=expires_at,
    )

    upload_url = (
        f"https://{account_name}.blob.core.windows.net/"
        f"{CONTAINER_NAME}/{blob_name}?{sas_token}"
    )

    result = {
        "request_id": request_id,
        "upload_url": upload_url,
        "blob_path": blob_name,
        "expires_at": expires_at.replace(microsecond=0).isoformat() + "Z",
        "max_size_bytes": MAX_UPLOAD_SIZE_BYTES,
        "required_headers": {
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": mime_type,
        },
        "allowed_content_types": sorted(ALLOWED_CONTENT_TYPES),
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        "submit_after_upload": True,
    }
    return json_rpc_success(result, rpc_id)


def _handle_submit(params: dict, rpc_id: str) -> func.HttpResponse:
    request_id = params.get("request_id")
    if not request_id:
        return json_rpc_error(
            -32602,
            "submit_manuscript requires 'request_id' from get_upload_url",
            rpc_id,
        )

    requested_filename = _sanitize_filename(params.get("filename"))
    mime_type = _guess_content_type(requested_filename, params.get("mime_type"))
    expected_size = params.get("size_bytes")
    expected_sha = params.get("sha256")
    staging_blob_name = _build_staging_blob_name(request_id, requested_filename)
    final_blob_name = _build_final_blob_name(request_id, requested_filename, mime_type)

    container_client = _get_container_client()
    staging_blob_client = container_client.get_blob_client(staging_blob_name)
    table_client = _get_table_client()

    if not staging_blob_client.exists():
        return json_rpc_error(
            -32602,
            "Uploaded blob not found. Call get_upload_url, upload the manuscript, then retry submit_manuscript.",
            rpc_id,
        )

    try:
        blob_props = staging_blob_client.get_blob_properties()
    except Exception as exc:
        logging.error(f"Failed to read staged blob properties: {exc}")
        return json_rpc_error(-32603, "Failed to inspect staged manuscript.", rpc_id)

    if expected_size is not None and blob_props.size != int(expected_size):
        return json_rpc_error(
            -32602,
            f"Uploaded blob size mismatch. Expected {expected_size}, found {blob_props.size}.",
            rpc_id,
        )

    actual_sha = blob_props.metadata.get("sha256") if blob_props.metadata else None
    if expected_sha and actual_sha and expected_sha != actual_sha:
        return json_rpc_error(-32602, "Uploaded blob checksum mismatch.", rpc_id)

    final_blob_client = container_client.get_blob_client(final_blob_name)
    try:
        final_blob_client.start_copy_from_url(staging_blob_client.url)
        final_blob_client.set_http_headers(content_settings=blob_props.content_settings)
    except Exception as exc:
        logging.error(f"Failed to finalize staged manuscript: {exc}")
        return json_rpc_error(-32603, "Failed to finalize uploaded manuscript.", rpc_id)

    entity = {
        "PartitionKey": "AMIE",
        "RowKey": request_id,
        "filename": final_blob_name,
        "status": "queued",
        "uploaded_at": datetime.datetime.utcnow().isoformat(),
        "a2a_original_filename": requested_filename,
        "a2a_blob_path": final_blob_name,
        "a2a_staging_blob_path": staging_blob_name,
        "a2a_content_type": mime_type,
        "analysis_started_at": None,
        "pipeline_version": "1.0",
    }
    if expected_size is not None:
        entity["a2a_size_bytes"] = int(expected_size)
    if expected_sha:
        entity["a2a_sha256"] = expected_sha

    try:
        table_client.create_entity(entity=entity)
    except Exception as exc:
        logging.error(f"Failed to create table entity: {exc}")
        return json_rpc_error(-32603, "Failed to save request metadata.", rpc_id)

    try:
        _get_queue_client().send_message(request_id)
    except Exception as exc:
        logging.error(f"Failed to enqueue job: {exc}")
        return json_rpc_error(-32603, "Failed to start processing pipeline.", rpc_id)

    result = {
        "request_id": request_id,
        "status": "queued",
        "normalized_status": "queued",
        "filename": final_blob_name,
        "estimated_processing": "2-5 minutes",
        "next_step": "Call get_status to retrieve results"
    }
    return json_rpc_success(result, rpc_id)


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

    if method == "get_upload_url":
        return _handle_get_upload_url(params, rpc_id)
    if method == "submit_manuscript":
        return _handle_submit(params, rpc_id)
    if method == "get_status":
        return _handle_get_status(params, rpc_id)
    return json_rpc_error(-32601, f"Method '{method}' not found", rpc_id)
