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

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# Retrieve connection string from Azure configuration
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AzureWebJobsStorage")
CONTAINER_NAME = "manuscript-uploads"
TABLE_NAME = "IngestionRequests"

# Initialize Clients
blob_service = BlobServiceClient.from_connection_string(
    AZURE_STORAGE_CONNECTION_STRING)
table_service = TableServiceClient.from_connection_string(
    AZURE_STORAGE_CONNECTION_STRING)
container_client = blob_service.get_container_client(CONTAINER_NAME)

# verifying container exists
try:
    container_client.create_container()
except Exception:
    pass

try:
    table_service.create_table_if_not_exists(table_name=TABLE_NAME)
except Exception:
    pass


@app.route(route="upload", methods=["POST"]) 
def upload(req: func.HttpRequest) -> func.HttpResponse:
    """
    Receives a file upload from the frontend, saves it to Azure Blob Storage,
    and logs metadata for Application Insights.
    """
    logging.info("Received upload request.")
    request_id = str(uuid.uuid4())

    try:
        # Get the uploaded file
        uploaded_file = req.files.get("file")

        if not uploaded_file:
            return func.HttpResponse("No file provided.", status_code=400)

        # Upload the file to Blob
        blob_client = container_client.get_blob_client(uploaded_file.filename)
        blob_client.upload_blob(uploaded_file.stream.read(), overwrite=True)
        logging.info(
            f"File '{uploaded_file.filename}' uploaded to blob storage.")

        # Build ingestion record
        entity = {
            "PartitionKey": "AMIE",
            "RowKey": request_id,
            "filename": uploaded_file.filename,
            "status": "uploaded",
            "uploaded_at": datetime.datetime.utcnow().isoformat()
        }

        # Insert into Table Storage
        table_client = table_service.get_table_client(TABLE_NAME)
        table_client.create_entity(entity=entity)

        return func.HttpResponse(
            json.dumps({
                "request_id": request_id,
                "message": "Upload successful!",
                "filename": uploaded_file.filename
            }),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Upload failed: {e}")
        return func.HttpResponse(f"Error: {e}", status_code=500)

# GET /requests


@app.route(route="requests", methods=["GET"])
def list_requests(req: func.HttpRequest) -> func.HttpResponse:
    """List all ingestion requests stored in Table Storage."""
    table_client = table_service.get_table_client(TABLE_NAME)
    entities = list(table_client.list_entities())
    results = [
        {
            "request_id": e["RowKey"],
            "filename": e["filename"],
            "status": e["status"],
            "uploaded_at": e.get("uploaded_at")
        }
        for e in entities
    ]
    return func.HttpResponse(json.dumps(results, indent=2), mimetype="application/json")


# GET /requests/{request_id}
@app.route(route="requests/{request_id}", methods=["GET"])
def get_request(req: func.HttpRequest) -> func.HttpResponse:
    """Retrieve one ingestion record."""
    request_id = req.route_params.get("request_id")
    table_client = table_service.get_table_client(TABLE_NAME)
    try:
        entity = table_client.get_entity(
            partition_key="AMIE", row_key=request_id)
        return func.HttpResponse(json.dumps(entity), mimetype="application/json")
    except Exception:
        return func.HttpResponse("Request not found", status_code=404)

# DELETE /requests/{request_id}


@app.route(route="requests/{request_id}", methods=["DELETE"])
def delete_request(req: func.HttpRequest) -> func.HttpResponse:
    """ Soft delete or cancel an ingestion request """
    request_id = req.route_params.get("request_id")
    table_client = table_service.get_table_client(TABLE_NAME)
    try:
        entity = table_client.get_entity(
            partition_key="AMIE", row_key=request_id)
        entity["status"] = "deleted"
        entity["deleted_at"] = datetime.datetime.utcnow().isoformat()
        table_client.update_entity(mode="merge", entity=entity)
        logging.info(f"Request {request_id} marked as deleted.")
        return func.HttpResponse(
            json.dumps({"message": f"Request {request_id} marked as deleted"}),
            mimetype="application/json",
            status_code=200
        )
    except Exception as e:
        logging.error(f"Failed to delete record: {e}")
        return func.HttpResponse(f"Request ID not found or could not be deleted: {e}", status_code=404)


# POST /requests/{request_id}/retry
@app.route(route="requests/{request_id}/retry", methods=["POST"])
def retry_request(req: func.HttpRequest) -> func.HttpResponse:
    """Retry a failed ingestion by setting status back to 'retrying'."""
    request_id = req.route_params.get("request_id")
    table_client = table_service.get_table_client(TABLE_NAME)
    try:
        entity = table_client.get_entity(
            partition_key="AMIE", row_key=request_id)
        old_status = entity.get("status")
        entity["status"] = "retrying"
        entity["retried_at"] = datetime.datetime.utcnow().isoformat()
        table_client.update_entity(mode="merge", entity=entity)

        logging.info(
            f"Request {request_id} retried (previous status: {old_status}).")
        return func.HttpResponse(
            json.dumps({
                "message": f"Retry initiated for request {request_id}",
                "previous_status": old_status,
                "new_status": "retrying"
            }),
            mimetype="application/json",
            status_code=200
        )
    except Exception as e:
        logging.error(f"Retry failed: {e}")
        return func.HttpResponse(f"Request ID not found or retry failed: {e}", status_code=404)


# GET /requests/{request_id}/status
@app.route(route="requests/{request_id}/status", methods=["GET"])
def get_status(req: func.HttpRequest) -> func.HttpResponse:
    """Return only the status of a given ingestion request."""
    request_id = req.route_params.get("request_id")
    table_client = table_service.get_table_client(TABLE_NAME)
    try:
        entity = table_client.get_entity(
            partition_key="AMIE", row_key=request_id)
        status = entity.get("status", "unknown")
        return func.HttpResponse(
            json.dumps({"request_id": request_id, "status": status}),
            mimetype="application/json",
            status_code=200
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
    table_client = table_service.get_table_client(TABLE_NAME)

    try:
        # Lookup blob info from Table Storage
        entity = table_client.get_entity(
            partition_key="AMIE",
            row_key=request_id
        )
        filename = entity["filename"]

        # Download file bytes from blob
        blob_client = container_client.get_blob_client(filename)
        data = blob_client.download_blob().readall()

        # Return PDF file bytes
        return func.HttpResponse(
            body=data,
            mimetype="application/pdf",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Download failed: {e}")
        return func.HttpResponse(f"Error: {e}", status_code=500)
    
    
@app.route(route="requests/{request_id}/text", methods=["GET"])
def get_text(req: func.HttpRequest) -> func.HttpResponse:
    """Return extracted text of the manuscript."""
    request_id = req.route_params.get("request_id")
    table_client = table_service.get_table_client(TABLE_NAME)

    try:
        # 1. Get metadata from table
        entity = table_client.get_entity(
            partition_key="AMIE",
            row_key=request_id
        )
        filename = entity["filename"]

        # 2. Download PDF bytes
        blob_client = container_client.get_blob_client(filename)
        pdf_bytes = blob_client.download_blob().readall()

        # 3. Extract text
        text = extract_pdf_text(pdf_bytes)

        if not text:
            return func.HttpResponse(
                "Text extraction failed or returned empty text.",
                status_code=422
            )

        # 4. Return JSON with the text
        return func.HttpResponse(
            json.dumps({
                "request_id": request_id,
                "filename": filename,
                "text": text
            }),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Failed to extract text: {e}")
        return func.HttpResponse(f"Error: {e}", status_code=500)

