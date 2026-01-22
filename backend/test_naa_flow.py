import os
import sys
import json
import logging
import asyncio
import io
import pathlib
from dotenv import load_dotenv

# Setup paths (same as function_app.py)
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]  # Go up to repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import checks
try:
    from backend.naa_brain_MVP.naa_test import run_steps_8_to_12
    from backend.naa_brain_MVP.rm_retrieval import download_and_store_rms
    from backend.naa_brain_MVP.rm_assessment import assess_all_rms
    from azure.data.tables import TableServiceClient
    from azure.storage.blob import BlobServiceClient
    from pypdf import PdfReader
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

# Constants
INGESTION_CONTAINER = "manuscript-uploads"
INGESTION_TABLE = "IngestionRequests"

def setup_logging():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_storage_clients():
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        # Try local settings
        local_settings_path = REPO_ROOT / "backend/ingestion-agent/local.settings.json"
        if local_settings_path.exists():
            with open(local_settings_path, 'r') as f:
                settings = json.load(f)
                conn_str = settings.get("Values", {}).get("AZURE_STORAGE_CONNECTION_STRING")
        
    if not conn_str:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING not found in env or local.settings.json")
        
    blob_service = BlobServiceClient.from_connection_string(conn_str)
    table_service = TableServiceClient.from_connection_string(conn_str)
    return blob_service, table_service

def extract_text(blob_service, blob_name):
    print(f"Downloading manuscript: {blob_name}...")
    container_client = blob_service.get_container_client(INGESTION_CONTAINER)
    blob_client = container_client.get_blob_client(blob_name)
    data = blob_client.download_blob().readall()
    
    if not blob_name.lower().endswith(".pdf"):
        return ""
        
    reader = PdfReader(io.BytesIO(data))
    text = ""
    for page in reader.pages:
        t = page.extract_text()
        if t: text += t + " "
    return text.strip()

async def run_naa_test(request_id):
    print(f"--- Starting Manual NAA Test for Request ID: {request_id} ---")
    
    # 1. Connect
    blob_service, table_service = get_storage_clients()
    table = table_service.get_table_client(INGESTION_TABLE)
    
    # 2. Get Entity
    try:
        entity = table.get_entity("AMIE", request_id)
        print(f"Found request. Status: {entity.get('status')}")
    except Exception as e:
        print(f"Error finding request {request_id}: {e}")
        return

    # 3. Check Prerequisites
    idca_output = entity.get("idca_output")
    filename = entity.get("filename")
    
    if not idca_output:
        print("ERROR: No idca_output found.")
        return
    if not filename:
        print("ERROR: No filename found.")
        return

    # 4. Get Manuscript Text
    manuscript_text = extract_text(blob_service, filename)
    if not manuscript_text:
        print("ERROR: Failed to extract text from manuscript.")
        return
    print(f"Manuscript text length: {len(manuscript_text)} chars")

    # 5. Run Steps 8-12 (SS -> UCS -> Search)
    print("\n--- Running Steps 8-12 ---")
    try:
        naa_outputs = await run_steps_8_to_12(manuscript_text, idca_output)
    except Exception as e:
        print(f"NAA Steps 8-12 Failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Check Search Results
    if not naa_outputs.lor:
        print("\nWARNING: No references found (empty LoR).")
    else:
        print(f"\nFound {len(naa_outputs.lor)} references.")

    # 6. Run Step 13 (Retrieve RMs)
    print("\n--- Running Step 13 (Reference Retrieval) ---")
    try:
        stored_blobs = await download_and_store_rms(request_id, naa_outputs.lor, blob_service)
        print(f"Stored {len(stored_blobs)} documents.")
    except Exception as e:
        print(f"Retrieval Failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # 7. Run Step 14 (Assessment) - Optional but good for full flow
    # Assuming assess_all_rms logic is standalone
    # Note: access_all_rms logic might not be fully imported/setup here depending on complexity
    # We will stop here as requested ("runs all the naa steps... see if the naa flow would work")
    
    print("\n--- Test Complete ---")

if __name__ == "__main__":
    setup_logging()
    load_dotenv()
    
    if len(sys.argv) < 2:
        print("Usage: python test_naa_flow.py <request_id>")
        sys.exit(1)
        
    req_id = sys.argv[1]
    asyncio.run(run_naa_test(req_id))
