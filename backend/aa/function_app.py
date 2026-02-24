"""Aggregation Agent (AA) Azure Function

POST /aa/run/{request_id}
--------------------------
Executes the Aggregation Agent to produce the final assessment report.
Reads IDCA and NAA outputs from Table Storage, runs the AA logic,
and persists the final report back to the table with status 'completed'.
"""

import azure.functions as func
import datetime
import json
import logging
import os
import pathlib
import sys
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient

from aa import run_aggregation_agent

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# Storage configuration
STORAGE = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv(
    "AzureWebJobsStorage"
)
TABLE_NAME = "IngestionRequests"
CONTAINER_NAME = "manuscript-uploads"


def _get_naa_output_str(entity) -> str:
    """Resolve NAA output from table property or from blob if too large."""
    blob_path = entity.get("naa_output_blob")
    if blob_path:
        blob_service = BlobServiceClient.from_connection_string(STORAGE)
        container = blob_service.get_container_client(CONTAINER_NAME)
        blob_client = container.get_blob_client(blob_path)
        data = blob_client.download_blob().readall()
        return data.decode("utf-8")
    return entity.get("naa_output", "{}") or "{}"


@app.route(route="aa/run/{request_id}", methods=["POST"])
def run_aa(req: func.HttpRequest) -> func.HttpResponse:
    """Execute Aggregation Agent for the given request-id."""
    request_id = req.route_params.get("request_id")
    if not request_id:
        return func.HttpResponse("Missing request_id", status_code=400)

    if not STORAGE:
        return func.HttpResponse(
            "Storage connection string not configured", status_code=500
        )

    try:
        from azure.data.tables import TableClient
        from azure.core import MatchConditions
        from datetime import datetime

        # 1. Idempotency Check & Job Claiming
        table_client = TableClient.from_connection_string(STORAGE, TABLE_NAME)
        
        try:
            entity = table_client.get_entity(partition_key="AMIE", row_key=request_id)
            status = entity.get("status", "").lower()
            
            # If already processing or done, skip
            if status != "assessed":
                logging.info(
                    f"AA cannot run from state '{status}'. Expected 'assessed'. Skipping."
                )
                return func.HttpResponse(
                    f"AA cannot run from state '{status}'.",
                    status_code=200,
            )

            # Note: We don't have a specific "aggregating" status in the current UI, 
            # but we can claim it to prevent overlapping runs.
            entity["aa_started_at"] = datetime.utcnow().isoformat()
            
            table_client.update_entity(
                entity, 
                mode='replace', 
                etag=entity.metadata.get('etag'),
                match_condition=MatchConditions.IfNotModified
            )
            logging.info(f"Successfully claimed AA job for {request_id}")

        except Exception as claim_err:
            if "ConditionNotMet" in str(claim_err) or "UpdateConditionNotSatisfied" in str(claim_err):
                logging.info(f"Race condition: AA Request {request_id} was recently claimed. Skipping.")
                return func.HttpResponse(f"Request {request_id} already claimed.", status_code=200)
            
            logging.error(f"Error checking/claiming AA job for {request_id}: {claim_err}")
            # Proceed anyway if it's just a read error
            entity = table_client.get_entity("AMIE", request_id)

        # Parse IDCA output
        idca_output_str = entity.get("idca_output", "{}")
        try:
            idca_output = json.loads(idca_output_str)
        except:
            idca_output = {}

        # Parse NAA output (from table or blob if stored there due to size)
        naa_output_str = _get_naa_output_str(entity)
        try:
            naa_output_dict = json.loads(naa_output_str) if naa_output_str else {}
        except:
            naa_output_dict = {}

        # Convert NAA output dict to object-like structure for compatibility
        class NAAOutput:
            def __init__(self, data):
                self.ss_synopsis = data.get("ss_synopsis", "")
                self.lor = data.get("lor", [])
                self.ucs = data.get("ucs", "")
                self.ssr = data.get("ssr", {})

        naa_output = NAAOutput(naa_output_dict) if naa_output_dict else None

        # Parse NAA assessments if present
        naa_assessments = naa_output_dict.get("assessments", [])

        # Run Aggregation Agent
        # Pass table=None to preventing double-write race condition
        logging.info(f"Running Aggregation Agent for request {request_id}")
        logging.info(f"AA received {len(naa_assessments)} NAA assessments")
        final_report = run_aggregation_agent(
            idca_output=idca_output,
            naa_output=naa_output,
            naa_assessments=naa_assessments,
            request_id=request_id,
            table=None,  # Do not let helper write to table; we do it here atomically
        )

        # Update status to completed
        entity["status"] = "completed"
        entity["completed_at"] = datetime.utcnow().isoformat()

        # Handle AA output storage (Blob if large, Table if small)
        blob_path = f"aa-outputs/{request_id}.md"
        report_bytes = final_report.encode("utf-8")
        
        if len(report_bytes) > 32 * 1024:  # > 32KB -> Blob
            logging.info(f"AA output too large ({len(report_bytes)} bytes), offloading to blob.")
            blob_service = BlobServiceClient.from_connection_string(STORAGE)
            container_client = blob_service.get_container_client(CONTAINER_NAME)
            blob_client = container_client.get_blob_client(blob_path)
            blob_client.upload_blob(report_bytes, overwrite=True)
            
            entity["aa_output_blob"] = blob_path
            entity.pop("aa_output", None) # Ensure no stale data
        else:
            entity["aa_output"] = final_report
            entity.pop("aa_output_blob", None)

        table_client.update_entity(entity)

        logging.info(f"AA completed for request {request_id}")
        return func.HttpResponse(
            f"Aggregation Agent completed for {request_id}",
            status_code=200,
            mimetype="text/plain",
        )

    except Exception as e:
        logging.error(f"AA failed for {request_id}: {e}", exc_info=True)
        return func.HttpResponse(f"AA failed: {e}", status_code=500)
