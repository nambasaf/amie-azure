import os
import io
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from pypdf import PdfReader
from azure.storage.blob import BlobServiceClient
from rm_retrieval import get_container_name
from naa_test import (
    _chat,
    SSR_AGENT_ID,
    render_ssr_table,
    StructuralScoringRubric,
    SSRItem,
)

# ---------------------------------------------------------------------
# DATA MODELS
# ---------------------------------------------------------------------


@dataclass
class RMAssessmentOutput:
    filename: str
    reference_citation: str
    rs_synopsis: str
    sos_score: Dict[str, Any]  # Contains CSS, EWSS, and itemized scores
    status_determination: str  # "Novel", "Not Novel", etc - derived from comparison


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """Extracts text from PDF or TXT files."""
    try:
        # Check file extension
        if filename.endswith(".txt"):
            # Decode text file
            return file_bytes.decode("utf-8")
        else:
            # Assume PDF
            with io.BytesIO(file_bytes) as f:
                reader = PdfReader(f)
                text = []
                for page in reader.pages:
                    text.append(page.extract_text() or "")
                return "\n".join(text)
    except Exception as e:
        logging.error(f"Failed to extract text from {filename}: {e}")
        return ""


def format_patent_citation(patent_data: dict) -> str:
    """
    Formats a patent citation in APA style.

    Format: Inventor(s). (Year). Title. U.S. Patent No. XXXXXXX. USPTO.

    Example:
    Smith, J., & Doe, A. (2023). Quantum computing apparatus.
    U.S. Patent No. 11,234,567. USPTO.
    """
    # Extract data
    inventors = patent_data.get("inventors", [])
    year = patent_data.get("year", "n.d.")
    title = patent_data.get("title", "Untitled Patent")
    patent_number = patent_data.get("patent_number", "Unknown")

    # Format inventors
    if inventors:
        if len(inventors) == 1:
            inventor_str = inventors[0]
        elif len(inventors) == 2:
            inventor_str = f"{inventors[0]}, & {inventors[1]}"
        else:
            inventor_str = f"{inventors[0]}, et al."
    else:
        inventor_str = "Unknown Inventor"

    # Build citation
    citation = (
        f"{inventor_str}. ({year}). {title}. U.S. Patent No. {patent_number}. USPTO."
    )

    return citation


def generate_assessment_prompt(rm_text: str, ssr_json: str, ss_summary: str) -> str:
    """Generates the prompt for the LLM to assess the RM."""

    # Truncate RM text to fit context if needed (approx 15k chars is usually safe for summary)
    # But for deep structural matching we want as much as possible.
    # Let's truncate to 30,000 characters to be safe with GPT-4 context limits if needed.
    truncated_text = rm_text[:30000]

    return f"""
You are the Novelty Assessment Agent. Your task is to Assess a Reference Manuscript (RM) against a Source Structure (SS) using a Structural Scoring Rubric (SSR).

SOURCE STRUCTURE SUMMARY:
{ss_summary}

STRUCTURAL SCORING RUBRIC (SSR):
{ssr_json}

REFERENCE MANUSCRIPT TEXT (Truncated):
{truncated_text}

==================================================
TASKS (Follow these steps and return the JSON below):
==================================================

1. Extract the Reference Structure (RS):
   - Map RM elements to SS blocks.
   - Record status (Present, Partial, Absent).
   - Cite evidence.

2. Apply SSR to Produce Structural Overlap Score (SOS):
   - Assign Match Score (0=Absent, 1=Partial, 2=Present) for each SS block.
   - Evidence-Weighted Similarity Score (EWSS) logic: 
     - 0 if Absent.
     - 1 * Weight if Partial (0.5 * Weight? No, instructions say 'includes elements...'). 
     - STRICT INSTRUCTION: 
       - CSS = Sum(Weight) for items with Score=2.
       - EWSS = Sum(Weight) for items with Score=1 OR 2.

3. RS Structural Synopsis:
   - One sentence: actor -> operation -> object/outcome.

4. Reference Citation:
   - APA Style format.

==================================================
OUTPUT FORMAT (JSON ONLY):
==================================================
Return ONLY valid JSON with this structure:

{{
  "reference_citation": "Author, A. (Year). Title...",
  "rs_synopsis": "The system...",
  "ss_match_scores": [
    {{
      "block_name": "SS Block Name 1",
      "match_score": 2,
      "status": "Present",
      "evidence": "Section 3.1 describes..."
    }},
    ...
  ],
  "css": 0.0,
  "ewss": 0.0,
  "novelty_status": "Provisional Novelty | Likely Anticipated"
}}

Note:
- "Likely Anticipated" if EWSS > 0.8 (High Overlap).
- "Provisional Novelty" if EWSS < 0.5 (Low Overlap).
- "Requires Expert Review" otherwise.
"""


import time
import random

# ---------------------------------------------------------------------
# ASYNC RETRY HELPER
# ---------------------------------------------------------------------
async def async_retry_agent(coro_fn, agent_name: str, max_attempts: int = 3):
    """
    Async retry wrapper with exponential backoff and jitter.
    """
    last_exception = None
    for attempt in range(1, max_attempts + 1):
        try:
            # Check if coro_fn is a coroutine object or a function that returns one
            if asyncio.iscoroutine(coro_fn):
                return await coro_fn
            else:
                return await coro_fn()
        except Exception as e:
            last_exception = e
            logging.warning(f"[RETRY] {agent_name} failed (Attempt {attempt}/{max_attempts}): {e}")
            if attempt < max_attempts:
                sleep_time = (2 ** attempt) + (random.uniform(0, 1))
                await asyncio.sleep(sleep_time)
            else:
                logging.error(f"[RETRY] {agent_name} exhausted all {max_attempts} attempts.")
    raise last_exception

# ---------------------------------------------------------------------
# SINGLE RM ASSESSMENT (SAFE WRAPPER)
# ---------------------------------------------------------------------
async def assess_single_rm(
    sem: asyncio.Semaphore,
    record: Dict[str, Any],
    container_client,
    ssr_json: str,
    ss_summary: str
) -> Dict[str, Any]:
    """
    Wraps the assessment logic for a single RM with concurrency control and retries.
    Updates the record in-place.
    """
    blob_name = record.get("blob_name")
    if not record.get("stored") or not blob_name:
        # Skip records that weren't stored
        return record

    async with sem:
        logging.info(f"[RM-ASSESSMENT] Starting: {blob_name}")
        try:
            # 1. Download
            blob_client = container_client.get_blob_client(blob_name)
            content = blob_client.download_blob().readall()

            # 2. Extract Text
            text = extract_text_from_file(content, blob_name)
            if len(text) < 500:
                record["error"] = f"Text too short ({len(text)} chars). Skipping."
                return record

            # 3. Assess with Retries
            prompt = generate_assessment_prompt(text, ssr_json=ssr_json, ss_summary=ss_summary)
            
            # Note: _chat is sync in naa_test.py. We need to run it in a thread if we want true async, 
            # or wrap it if it's already async. In naa_test.py it looks sync.
            # For now, let's wrap the sync _chat in to_thread.
            
            async def _do_chat():
                return await asyncio.to_thread(_chat, SSR_AGENT_ID, prompt)

            response_json_str = await async_retry_agent(_do_chat, f"SSR Agent ({blob_name})")
            
            # 4. Parse
            data = json.loads(response_json_str)
            
            # Update record
            record["assessed"] = True
            record["assessment"] = data
            record["status_determination"] = data.get("novelty_status", "Unknown")
            record["ewss"] = data.get("ewss", 0.0)
            
            logging.info(f"  -> Analyzed {blob_name}. Status: {record['status_determination']} (EWSS: {record['ewss']})")

        except Exception as e:
            err_msg = f"Assessment failed for {blob_name}: {str(e)}"
            logging.error(err_msg)
            record["assessed"] = False
            record["error"] = err_msg

    return record

# ---------------------------------------------------------------------
# MAIN ASSESSMENT FUNCTION
# ---------------------------------------------------------------------

async def assess_all_rms(
    req_id: str,
    blob_service_client: BlobServiceClient,
    ssr: StructuralScoringRubric,
    ss_summary: str,
    retrieval_records: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    1. Filter retrieval_records to those that were successfully stored.
    2. Capping at MAX_RMS_TO_ASSESS (env) or 250.
    3. Run parallel assessments with Semaphore.
    4. Return original records list (updated).
    """
    max_to_assess = int(os.getenv("MAX_RMS_TO_ASSESS", 250))
    max_concurrent = int(os.getenv("MAX_CONCURRENT_ASSESSMENTS", 10))
    sem = asyncio.Semaphore(max_concurrent)

    container_name = get_container_name(req_id)
    container_client = blob_service_client.get_container_client(container_name)

    if not container_client.exists():
        logging.warning(f"Container {container_name} not found. Skipping assessment.")
        return retrieval_records

    # Convert SSR to JSON string for prompt
    ssr_dict = {
        "items": [
            {
                "block_name": i.block_name,
                "weight": i.weight,
                "match_criteria": i.match_criteria,
            }
            for i in ssr.items
        ]
    }
    ssr_json = json.dumps(ssr_dict, indent=2)

    # 1. First, filter only valid stored records to prioritize them
    stored_records = [r for r in retrieval_records if r.get("stored")]
    
    # 2. Apply the cap (e.g., top 250 of successfully stored records)
    if len(stored_records) > max_to_assess:
        logging.info(f"[RM-ASSESSMENT] Truncating stored records from {len(stored_records)} to {max_to_assess}")
        task_records = stored_records[:max_to_assess]
    else:
        task_records = stored_records

    # Prepare tasks
    tasks = []
    for record in task_records:
        # Initialize assessment fields
        record["assessed"] = False
        record["assessment"] = None
        tasks.append(assess_single_rm(sem, record, container_client, ssr_json, ss_summary))

    if tasks:
        logging.info(f"[RM-ASSESSMENT] Dispatching {len(tasks)} parallel assessments (Concurrency: {max_concurrent})...")
        await asyncio.gather(*tasks)

    # The retrieval_records list has been updated in-place (or we return the task_records slice if we want)
    # To be safe and preserve original list length/mapping, we return retrieval_records.
    return retrieval_records
