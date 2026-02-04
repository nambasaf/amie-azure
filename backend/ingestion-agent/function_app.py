import azure.functions as func
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient, TableEntity
import logging
import os
import uuid
import datetime
import json

import tempfile
from PyPDF2 import PdfReader
from azure.storage.queue import QueueClient, TextBase64EncodePolicy
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ResourceExistsError


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# Retrieve connection string (prefer explicit var, fallback to default)

CONTAINER_NAME = "manuscript-uploads"
TABLE_NAME = "IngestionRequests"

STORAGE_ACCOUNT_NAME = os.getenv("STORAGE_ACCOUNT_NAME")

def get_queue_client():
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
    if not conn_str:
        raise RuntimeError("No storage connection string found")

    queue_client = QueueClient.from_connection_string(
        conn_str,
        queue_name="idca-queue",
        message_encode_policy=TextBase64EncodePolicy()
    )

    # Create queue if it doesn't exist
    try:
        queue_client.create_queue()
    except ResourceExistsError:
        pass  # queue already exists, safe to ignore

    return queue_client


def get_blob_service():
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
    if conn_str:
        return BlobServiceClient.from_connection_string(conn_str)
        
    if not STORAGE_ACCOUNT_NAME:
        raise RuntimeError("Neither AZURE_STORAGE_CONNECTION_STRING nor STORAGE_ACCOUNT_NAME is set")

    return BlobServiceClient(
        account_url=f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net",
        credential=DefaultAzureCredential(),
    )

def get_table_service():
    conn_str = os.getenv("TABLE_CONNECTION_STRING") or os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
    if conn_str:
        return TableServiceClient.from_connection_string(conn_str)

    if not STORAGE_ACCOUNT_NAME:
        raise RuntimeError("Neither connection string nor STORAGE_ACCOUNT_NAME is set")

    return TableServiceClient(
        endpoint=f"https://{STORAGE_ACCOUNT_NAME}.table.core.windows.net",
        credential=DefaultAzureCredential(),
    )

def get_table_client():
    service = get_table_service()
    service.create_table_if_not_exists(TABLE_NAME)
    return service.get_table_client(TABLE_NAME)

    
@app.route(route="upload", methods=["POST"])
def upload(req: func.HttpRequest) -> func.HttpResponse:
    """
    Receives a file upload from the frontend, saves it to Azure Blob Storage,
    and enqueues an IDCA job for background processing.
    """
    logging.info("Received upload request.")
    request_id = str(uuid.uuid4())

    try:
        uploaded_file = req.files.get("file")
        if not uploaded_file:
            return func.HttpResponse("No file provided.", status_code=400)

        # Upload file to Blob Storage
        blob_service = get_blob_service()
        container_client = blob_service.get_container_client(CONTAINER_NAME)
        blob_client = container_client.get_blob_client(uploaded_file.filename)  
        blob_client.upload_blob(uploaded_file.stream.read(), overwrite=True)

        # Create ingestion record
        entity = {
            "PartitionKey": "AMIE",
            "RowKey": request_id,
            "filename": uploaded_file.filename,
            "status": "uploaded",
            "uploaded_at": datetime.datetime.utcnow().isoformat(),
        }

        table_service = get_table_service()
        table_client = table_service.get_table_client(TABLE_NAME)
        table_client.create_entity(entity=entity)

        # Enqueue IDCA job
        try:
            queue_client = get_queue_client()
            queue_client.send_message(request_id)
            entity["status"] = "queued"
            table_client.update_entity(mode="merge", entity=entity)
        except Exception:
            logging.error("Failed to enqueue IDCA job", exc_info=True)
            entity["status"] = "enqueue_failed"
            table_client.update_entity(mode="merge", entity=entity)
            return func.HttpResponse(
                "Upload succeeded but failed to queue processing job",
                status_code=500,
            )

        return func.HttpResponse(
            json.dumps(
                {
                    "request_id": request_id,
                    "message": "Upload successful!",
                    "filename": uploaded_file.filename,
                }
            ),
            mimetype="application/json",
            status_code=200,
        )

    except Exception:
        logging.error("Upload failed", exc_info=True)
        return func.HttpResponse("Internal server error", status_code=500)



# GET /requests


@app.route(route="requests", methods=["GET"])
def list_requests(req: func.HttpRequest) -> func.HttpResponse:
    """List all ingestion requests stored in Table Storage."""
    table_client = get_table_client()
    entities = list(table_client.list_entities())
    results = [
    {
        "request_id": e.get("RowKey"),
        "filename": e.get("filename", None),
        "status": e.get("status", "unknown"),
        "uploaded_at": e.get("uploaded_at"),
    }
    for e in entities
]

    return func.HttpResponse(json.dumps(results, indent=2), mimetype="application/json")


def _entity_to_response_dict(entity, blob_service=None):
    """Build a JSON-serializable dict from a table entity; resolve blobs if stored there."""
    result = dict(entity)

    # Resolve NAA output
    if result.get("naa_output_blob") and blob_service:
        try:
            container = blob_service.get_container_client(CONTAINER_NAME)
            blob_client = container.get_blob_client(result["naa_output_blob"])
            data = blob_client.download_blob().readall()
            result["naa_output"] = data.decode("utf-8")
        except Exception as e:
            logging.warning(f"Could not load naa_output from blob: {e}")
        result.pop("naa_output_blob", None)

    # Resolve AA output
    if result.get("aa_output_blob") and blob_service:
        try:
            container = blob_service.get_container_client(CONTAINER_NAME)
            blob_client = container.get_blob_client(result["aa_output_blob"])
            data = blob_client.download_blob().readall()
            result["aa_output"] = data.decode("utf-8")
        except Exception as e:
            logging.warning(f"Could not load aa_output from blob: {e}")
        result.pop("aa_output_blob", None)

    return result


# GET /requests/{request_id}
@app.route(route="requests/{request_id}", methods=["GET"])
def get_request(req: func.HttpRequest) -> func.HttpResponse:
    """Retrieve one ingestion record."""
    request_id = req.route_params.get("request_id")
    table_service = get_table_service()
    table_client = table_service.get_table_client(TABLE_NAME)
    try:
        entity = table_client.get_entity(partition_key="AMIE", row_key=request_id)
        blob_service = get_blob_service()
        payload = _entity_to_response_dict(entity, blob_service)
        return func.HttpResponse(json.dumps(payload), mimetype="application/json")
    except Exception:
        return func.HttpResponse("Request not found", status_code=404)


# DELETE /requests/{request_id}


@app.route(route="requests/{request_id}", methods=["DELETE"])
def delete_request(req: func.HttpRequest) -> func.HttpResponse:
    """Soft delete or cancel an ingestion request"""
    request_id = req.route_params.get("request_id")
    table_service = get_table_service()
    table_client = table_service.get_table_client(TABLE_NAME)
    try:
        entity = table_client.get_entity(partition_key="AMIE", row_key=request_id)
        entity["status"] = "deleted"
        entity["deleted_at"] = datetime.datetime.utcnow().isoformat()
        table_client.update_entity(mode="merge", entity=entity)
        logging.info(f"Request {request_id} marked as deleted.")
        return func.HttpResponse(
            json.dumps({"message": f"Request {request_id} marked as deleted"}),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as e:
        logging.error(f"Failed to delete record: {e}")
        return func.HttpResponse(
            f"Request ID not found or could not be deleted: {e}", status_code=404
        )


# POST /requests/{request_id}/retry
@app.route(route="requests/{request_id}/retry", methods=["POST"])
def retry_request(req: func.HttpRequest) -> func.HttpResponse:
    """Retry a failed ingestion by setting status back to 'retrying'."""
    request_id = req.route_params.get("request_id")
    table_service = get_table_service()
    table_client = table_service.get_table_client(TABLE_NAME)
    try:
        entity = table_client.get_entity(partition_key="AMIE", row_key=request_id)
        old_status = entity.get("status")
        entity["status"] = "retrying"
        entity["retried_at"] = datetime.datetime.utcnow().isoformat()
        table_client.update_entity(mode="merge", entity=entity)

        logging.info(f"Request {request_id} retried (previous status: {old_status}).")
        return func.HttpResponse(
            json.dumps(
                {
                    "message": f"Retry initiated for request {request_id}",
                    "previous_status": old_status,
                    "new_status": "retrying",
                }
            ),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as e:
        logging.error(f"Retry failed: {e}")
        return func.HttpResponse(
            f"Request ID not found or retry failed: {e}", status_code=404
        )


# GET /requests/{request_id}/status
@app.route(route="requests/{request_id}/status", methods=["GET"])
def get_status(req: func.HttpRequest) -> func.HttpResponse:
    """Return only the status of a given ingestion request."""
    request_id = req.route_params.get("request_id")
    table_service = get_table_service()
    table_client = table_service.get_table_client(TABLE_NAME)
    try:
        entity = table_client.get_entity(partition_key="AMIE", row_key=request_id)
        status = entity.get("status", "unknown")
        return func.HttpResponse(
            json.dumps({"request_id": request_id, "status": status}),
            mimetype="application/json",
            status_code=200,
        )
    except Exception:
        return func.HttpResponse("Request not found", status_code=404)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extracts plain text from PDF bytes using PyPDF2."""
    try:
        # write PDF bytes to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        # extract text from PDF
        reader = PdfReader(tmp_path)
        extracted = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                extracted.append(text)

        final_text = "\n".join(extracted).strip()
        return final_text

    except Exception as e:
        logging.error(f"PDF text extraction failed: {e}")
        raise


@app.route(route="requests/{request_id}/file", methods=["GET"])
def download_file(req: func.HttpRequest) -> func.HttpResponse:
    """Return raw PDF bytes for the given request."""
    request_id = req.route_params.get("request_id")
    table_service = get_table_service()
    table_client = table_service.get_table_client(TABLE_NAME)

    try:
        # Lookup blob info from Table Storage
        entity = table_client.get_entity(partition_key="AMIE", row_key=request_id)
        filename = entity["filename"]

        # Download file bytes from blob
        blob_service = get_blob_service()
        container_client = blob_service.get_container_client(CONTAINER_NAME)
        blob_client = container_client.get_blob_client(filename)
        data = blob_client.download_blob().readall()

        # Return PDF file bytes
        return func.HttpResponse(body=data, mimetype="application/pdf", status_code=200)

    except Exception as e:
        logging.error(f"Download failed: {e}")
        return func.HttpResponse(f"Error: {e}", status_code=500)


@app.route(route="requests/{request_id}/text", methods=["GET"])
def get_text(req: func.HttpRequest) -> func.HttpResponse:
    """Return extracted text of the manuscript."""
    request_id = req.route_params.get("request_id")
    table_service = get_table_service()
    table_client = table_service.get_table_client(TABLE_NAME)   

    try:
        # 1. Get metadata from table
        entity = table_client.get_entity(partition_key="AMIE", row_key=request_id)
        filename = entity["filename"]

        # 2. Download PDF bytes
        blob_service = get_blob_service()
        container_client = blob_service.get_container_client(CONTAINER_NAME)
        blob_client = container_client.get_blob_client(filename)
        pdf_bytes = blob_client.download_blob().readall()

        # 3. Extract text
        text = extract_pdf_text(pdf_bytes)

        if not text:
            return func.HttpResponse(
                "Text extraction failed or returned empty text.", status_code=422
            )

        # 4. Return JSON with the text
        return func.HttpResponse(
            json.dumps({"request_id": request_id, "filename": filename, "text": text}),
            mimetype="application/json",
            status_code=200,
        )

    except Exception as e:
        logging.error(f"Failed to extract text: {e}")
        return func.HttpResponse(f"Error: {e}", status_code=500)


# Import queue workers so Azure Functions registers them
import idca_queue  # noqa: F401