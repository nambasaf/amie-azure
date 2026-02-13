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


# Cap RM assessments to stay within function timeout (~10 min with sequential LLM runs)
MAX_RMS_TO_ASSESS = 5

# ---------------------------------------------------------------------
# MAIN ASSESSMENT FUNCTION
# ---------------------------------------------------------------------


async def assess_all_rms(
    req_id: str,
    blob_service_client: BlobServiceClient,
    ssr: StructuralScoringRubric,
    ss_summary: str,
    ordered_blob_names: Optional[List[str]] = None,
) -> List[RMAssessmentOutput]:
    """
    1. List blobs in {reqID}_RMs (or use ordered_blob_names if provided = search order = best first)
    2. For each file (PDF or TXT):
       - Download & Extract Text
       - Run Assessment Agent (SSR_AGENT_ID)
       - Parse Result
    3. Return list of assessments

    If ordered_blob_names is provided (from download_and_store_rms), we assess the first
    MAX_RMS_TO_ASSESS in that order = the 5 best RMs from progressive search.
    """
    container_name = get_container_name(req_id)
    container_client = blob_service_client.get_container_client(container_name)

    if not container_client.exists():
        logging.warning(f"Container {container_name} not found. Skipping assessment.")
        return []

    assessments = []

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

    # Use search order (best first) if we have it; else fall back to list_blobs order
    if ordered_blob_names:
        blob_names_to_process = ordered_blob_names[:MAX_RMS_TO_ASSESS]
        if len(ordered_blob_names) > MAX_RMS_TO_ASSESS:
            logging.info(
                f"[RM-ASSESSMENT] Using top {MAX_RMS_TO_ASSESS} RMs in search order (total stored: {len(ordered_blob_names)})"
            )
    else:
        blobs = list(container_client.list_blobs())
        eligible = [b for b in blobs if b.name.endswith(".pdf") or b.name.endswith(".txt")]
        blob_names_to_process = [b.name for b in eligible[:MAX_RMS_TO_ASSESS]]
        if len(eligible) > MAX_RMS_TO_ASSESS:
            logging.info(
                f"[RM-ASSESSMENT] Capping at {MAX_RMS_TO_ASSESS} RMs (total eligible: {len(eligible)})"
            )

    for blob_name in blob_names_to_process:
        logging.info(f"\n[RM-ASSESSMENT] Processing: {blob_name}")

        try:
            # 1. Download (Sync)
            blob_client = container_client.get_blob_client(blob_name)
            content = blob_client.download_blob().readall()

            # 2. Extract Text (handles both PDF and TXT)
            text = extract_text_from_file(content, blob_name)
            if len(text) < 500:
                logging.warning(
                    f"Text too short ({len(text)} chars). Skipping LLM assessment."
                )
                continue

            # 3. Assess (Synchronous call to _chat inside async loop - blocked but ok for MVP)
            prompt = generate_assessment_prompt(text, ssr_json, ss_summary)

            response_json_str = _chat(SSR_AGENT_ID, prompt)

            # 4. Parse
            try:
                data = json.loads(response_json_str)

                # Create Output Object
                assessment = RMAssessmentOutput(
                    filename=blob_name,
                    reference_citation=data.get("reference_citation", "Unknown"),
                    rs_synopsis=data.get("rs_synopsis", ""),
                    sos_score={
                        "css": data.get("css", 0.0),
                        "ewss": data.get("ewss", 0.0),
                        "details": data.get("ss_match_scores", []),
                    },
                    status_determination=data.get("novelty_status", "Unknown"),
                )
                assessments.append(assessment)

                print(
                    f"  -> Analyzed. Status: {assessment.status_determination} (EWSS: {assessment.sos_score['ewss']})"
                )

            except json.JSONDecodeError:
                logging.error(f"Failed to parse JSON response for {blob_name}")
                logging.debug(f"Raw response: {response_json_str}")

        except Exception as e:
            logging.error(f"Error checking {blob_name}: {e}")

    return assessments
