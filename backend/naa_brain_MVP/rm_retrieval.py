import os
import logging
import asyncio
import threading
import time
import re
import httpx
from typing import List, Dict, Any
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError

async def resolve_pdf_url(url: str, client: httpx.AsyncClient) -> str:
    """
    Resolves a landing page URL (like OpenAlex ID) to a direct PDF URL.
    """
    # Case 1: OpenAlex Work ID (e.g., https://openalex.org/W4385273541)
    if "openalex.org/W" in url:
        try:
            work_id = url.split("/")[-1]
            api_url = f"https://api.openalex.org/works/{work_id}"
            logging.info(f"Resolving OpenAlex ID: {work_id} -> API")
            
            resp = await client.get(api_url)
            if resp.status_code == 200:
                data = resp.json()
                # Strategy: Try 'open_access.oa_url' first (often direct PDF)
                # Then 'primary_location.pdf_url'
                oa_url = data.get("open_access", {}).get("oa_url")
                pdf_url = data.get("primary_location", {}).get("pdf_url")
                
                final_url = pdf_url if pdf_url else oa_url
                if final_url:
                    logging.info(f"Resolved to: {final_url}")
                    return final_url
                else:
                    logging.warning(f"No PDF URL found in metadata for {work_id}")
                    return None
        except Exception as e:
            logging.warning(f"Failed to resolve OpenAlex URL: {e}")
            return None
            
    # Default: Return original URL
    return url

async def download_pdf(url: str) -> bytes:
    """Downloads PDF content from a URL with validation."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        # 1. Resolve URL if it's a landing page
        resolved_url = await resolve_pdf_url(url, client)
        if not resolved_url:
            raise ValueError("Could not resolve to a PDF URL")
            
        # 2. Download
        logging.info(f"Fetching: {resolved_url}")
        resp = await client.get(resolved_url)
        resp.raise_for_status()
        
        content = resp.content
        
        # 3. Validate
        # Content-Type check (permissive)
        ctype = resp.headers.get("Content-Type", "").lower()
        if "text/html" in ctype:
            raise ValueError(f"Got HTML instead of PDF (Content-Type: {ctype})")
            
        # Size Check (Real PDFs are usually > 10KB)
        if len(content) < 10_000:
            raise ValueError(f"File too small ({len(content)} bytes) to be a valid PDF.")
            
        return content


async def retrieve_patent_text(patent_id: str, api_key: str) -> str:
    """
    Retrieves patent text from PatentsView API.
    
    Priority (MVP):
    1. Independent claims only
    2. Fallback to abstract if claims unavailable
    3. Truncate to 30,000 characters for LLM context limits
    
    Returns plain text string.
    """
    url = "https://api.patentsview.org/patents/query"
    
    # Query for specific patent
    payload = {
        "q": {"patent_number": patent_id},
        "f": [
            "patent_number",
            "patent_title",
            "patent_abstract",
            "claims"
        ]
    }
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            headers = {"X-Api-Key": api_key}
            resp = await client.post(url, json=payload, headers=headers)
            
            if resp.status_code != 200:
                logging.error(f"PatentsView API error {resp.status_code}: {resp.text}")
                raise ValueError(f"Failed to retrieve patent {patent_id}")
            
            data = resp.json()
            patents = data.get("patents", [])
            
            if not patents:
                raise ValueError(f"Patent {patent_id} not found")
            
            patent = patents[0]
            
            # Extract claims (list of claim objects)
            claims = patent.get("claims", [])
            
            # Filter for independent claims only (claim_sequence starts with 1, 2, etc.)
            # Independent claims typically don't have dependencies
            independent_claims = []
            for claim in claims:
                claim_text = claim.get("claim_text", "")
                # Simple heuristic: independent claims are usually first few and don't start with "The ... of claim"
                if claim_text and not claim_text.strip().lower().startswith(("the", "a")):
                    independent_claims.append(claim_text)
                # Limit to first 3 independent claims for MVP
                if len(independent_claims) >= 3:
                    break
            
            # Build text content
            if independent_claims:
                text = "\n\n".join([f"Claim {i+1}: {c}" for i, c in enumerate(independent_claims)])
            else:
                # Fallback to abstract
                text = patent.get("patent_abstract", "")
                if not text:
                    raise ValueError(f"No claims or abstract available for patent {patent_id}")
            
            # Truncate to 30,000 characters
            if len(text) > 30000:
                text = text[:30000] + "\n\n[Truncated for context limits]"
            
            return text
            
    except Exception as e:
        logging.error(f"Failed to retrieve patent text for {patent_id}: {e}")
        raise


def sanitize_name(name: str) -> str:
    """Sanitizes string for use in blob names."""
    # Allow alphanumeric, dashes, underscores. Replace spaces with underscores.
    s = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name)
    # Truncate to limit length so blob name isn't too long
    return s[:100]

def get_container_name(req_id: str) -> str:
    """Generates valid container name from req_id."""
    # Container names must be lowercase, alphanumeric/dash, 3-63 chars
    clean_id = req_id.lower().replace("_", "-")
    return f"{clean_id}-rms"

def cleanup_container(container_name: str, blob_service_client: BlobServiceClient):
    """Deletes the temporary container."""
    try:
        logging.info(f"[RM-LIFECYCLE] Deleting temporary container: {container_name}")
        blob_service_client.delete_container(container_name)
        logging.info(f"[RM-LIFECYCLE] Container {container_name} deleted successfully.")
    except Exception as e:
        logging.error(f"[RM-LIFECYCLE] Failed to delete container {container_name}: {e}")

def schedule_cleanup(container_name: str, blob_service_client: BlobServiceClient, delay_seconds: int = 900):
    """Schedules container deletion in a background thread."""
    def worker():
        logging.info(f"[RM-LIFECYCLE] Sleeping {delay_seconds}s before cleanup of {container_name}...")
        time.sleep(delay_seconds)
        cleanup_container(container_name, blob_service_client)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    logging.info(f"[RM-LIFECYCLE] Cleanup scheduled for {container_name} in {delay_seconds} seconds.")

async def process_single_rm(rm: Dict[str, Any], container_client, api_key: str = None) -> str:
    """Downloads one RM (paper or patent) and uploads it to the container."""
    url = rm.get("url")
    title = rm.get("title", "untitled")
    source = rm.get("source", "Unknown")
    
    if not url:
        return None

    try:
        blob_name = f"{sanitize_name(title)}_{int(time.time())}"
        
        # Branch based on source type
        if source == "PatentsView":
            # Extract patent ID from URL or rm dict
            patent_id = rm.get("id")
            if not patent_id:
                logging.warning(f"No patent ID for '{title}'")
                return None
            
            if not api_key:
                logging.error("PATENTS_VIEW_KEY required for patent retrieval")
                return None
            
            # Retrieve patent text
            logging.info(f"Retrieving patent text for {patent_id}...")
            content = await retrieve_patent_text(patent_id, api_key)
            blob_name += ".txt"
            
            # Upload as text
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(content.encode('utf-8'), overwrite=True)
            logging.info(f"Stored patent: {blob_name} ({len(content)} chars)")
        
        else:
            # Default: Download PDF (for OpenAlex and other sources)
            blob_name += ".pdf"
            content = await download_pdf(url)
            
            # Upload PDF
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(content, overwrite=True)
            logging.info(f"Stored PDF: {blob_name} ({len(content)} bytes)")
        
        return blob_name
        
    except Exception as e:
        logging.warning(f"Failed to process RM '{title}': {str(e)}")
        return None

async def download_and_store_rms(req_id: str, lor: List[Dict[str, Any]], blob_service_client: BlobServiceClient):
    """
    Main entry point:
    1. Creates container reqID_RMs
    2. Downloads docs from LoR (PDFs for papers, text for patents)
    3. Stores them
    4. Schedules cleanup
    """
    import os
    
    container_name = get_container_name(req_id)
    logging.info(f"\n[RM-RETRIEVAL] Starting retrieval for {req_id} into {container_name}")
    
    # Get API key for patent retrieval
    api_key = os.getenv("PATENTS_VIEW_KEY")
    
    # 1. Create Container
    try:
        container_client = blob_service_client.create_container(container_name)
    except ResourceExistsError:
        container_client = blob_service_client.get_container_client(container_name)
        logging.info(f"Container {container_name} already exists.")
    
    # 2. Process URLs concurrently
    tasks = []
    for rm in lor:
        tasks.append(process_single_rm(rm, container_client, api_key))
        
    stored_blobs = await asyncio.gather(*tasks)
    
    # Filter Nones
    stored_blobs = [b for b in stored_blobs if b]
    
    logging.info(f"[RM-RETRIEVAL] Successfully stored {len(stored_blobs)}/{len(lor)} references.")
    
    # 3. Schedule Cleanup (15 mins = 900s)
    schedule_cleanup(container_name, blob_service_client, delay_seconds=900)
    
    return stored_blobs
