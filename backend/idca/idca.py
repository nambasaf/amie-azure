import os
import sys

# Ensure backend root directory is on import path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)


from dotenv import load_dotenv
from azure.ai.agents import AgentsClient

# from azure.ai.agents.models import MessageRole, ListSortOrder
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient
from azure.ai.agents.models import MessageRole
from PyPDF2 import PdfReader
import tempfile
from backend.aa.aa import run_aggregation_agent
from backend.utils.retry import retry_agent


# Load .env variables
load_dotenv()

# ------------------- ENV -------------------
PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT")
MODEL_DEPLOYMENT = os.getenv("MODEL_DEPLOYMENT")
# Storage can come from env or CLI arg (CLI arg takes precedence)
AZURE_STORAGE_CONNECTION_STRING = os.getenv(
    "AZURE_STORAGE_CONNECTION_STRING"
) or os.getenv("AzureWebJobsStorage")

if not PROJECT_ENDPOINT:
    raise ValueError(" PROJECT_ENDPOINT missing in .env")

if not MODEL_DEPLOYMENT:
    raise ValueError(" MODEL_DEPLOYMENT missing in .env")

CONTAINER_NAME = "manuscript-uploads"
TABLE_NAME = "IngestionRequests"

# ------------------- Azure Clients -------------------
agents_client = AgentsClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(
        exclude_environment_credential=True, exclude_managed_identity_credential=True
    ),
)

# Storage clients - will be initialized with connection string (from env or CLI)
blob_service = None
table_service = None
container = None
table = None

RUN_NAA = False


def init_storage_clients(connection_string: str):
    """Initialize storage clients with the given connection string."""
    global blob_service, table_service, container, table
    blob_service = BlobServiceClient.from_connection_string(connection_string)
    table_service = TableServiceClient.from_connection_string(connection_string)
    container = blob_service.get_container_client(CONTAINER_NAME)
    table = table_service.get_table_client(TABLE_NAME)


# Initialize with env var if available (for direct imports)
if AZURE_STORAGE_CONNECTION_STRING:
    init_storage_clients(AZURE_STORAGE_CONNECTION_STRING)

# ------------------- IDCA Behavior Prompt -------------------
IDCA_PROMPT = """
You are the Invention Detection and Classification Agent (IDCA) in the AMIE system.

You analyze a Source Manuscript (SM) and determine whether it discloses a concrete and useful Source Technology (ST).

Follow these rules exactly:

===========================================
1. STATUS DETERMINATION
===========================================
Determine:
- “Present” if the SM discloses a concrete, buildable, operational technology.
- “Implied” if a technology is suggested but incomplete.
- “Absent” if no technology is disclosed.

===========================================
2. FIELDS MAP
===========================================
If status = Present:
Return a short list of scientific or engineering fields required to understand the technology.

===========================================
3. SOURCE STRUCTURE (SS)
===========================================
If status = Present:
Decompose the technology into 3–8 structural elements (not functions, not background).
Each element must be:
- A physical or computational module
- A subsystem
- A processing block
- A real structural component

Write them as a bullet list of nouns ONLY.

Example:
- Neural signal acquisition module
- Spiking neural network processor
- Closed-loop controller

===========================================
4. STRUCTURAL SYNOPSIS (One Sentence)
===========================================
Write a ONE-SENTENCE summary of the SS following:
actor → operation → object/outcome

Rules:
- present tense
- plain English
- no performance claims
- no background theory
- must use ONLY SS element names

===========================================
5. OUTPUT FORMAT (MANDATORY)
===========================================
Return ONLY this JSON:

{
  "status_determination": "Present | Implied | Absent",
  "justification": "Short explanation.",
  "source_citation": "APA citation.",
  "fields_map": ["Field 1", "Field 2"],
  "source_structure": ["Element 1", "Element 2"],
  "structural_synopsis": "One sentence."
}

Do NOT include any other text.

"""

# connect to our IDCA agent on Azure AI Foundry
IDCA_AGENT_ID = os.getenv("IDCA_AGENT_ID")

if not IDCA_AGENT_ID:
    raise ValueError("Missing IDCA_AGENT_ID in .env")


# ------------------- Helpers -------------------
def get_manuscript_text(request_id: str) -> str:
    try:
        entity = table.get_entity("AMIE", request_id)
    except:
        raise ValueError(f" No record found for request_id: {request_id}")

    filename = entity.get("filename")
    print(entity["filename"])
    if not filename:
        raise ValueError(" filename missing in table record.")

    # Download PDF bytes
    blob = container.get_blob_client(filename)
    pdf_bytes = blob.download_blob().readall()

    # Write to temporary file for parsing
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    # Extract text
    reader = PdfReader(tmp_path)
    extracted = []
    for page in reader.pages:
        extracted.append(page.extract_text() or "")  # avoid None

    text = "\n".join(extracted).strip()

    if not text or len(text) < 100:
        print(" PyPDF2 returned very little text — this PDF may be scanned.")
        print("→ If so, we will need to switch to pdfminer or OCR.")

    return text


# some are too large
def send_in_chunks(thread_id, text, chunk_size=5000):
    for i in range(0, len(text), chunk_size):
        agents_client.messages.create(
            thread_id=thread_id, role=MessageRole.USER, content=text[i : i + chunk_size]
        )


# ------------------- Run IDCA -------------------
def run_idca(request_id: str):
    manuscript = get_manuscript_text(request_id)
    print("\n--- MANUSCRIPT SIZE:", len(manuscript), "characters ---\n")

    # Define the retryable IDCA agent execution
    def execute_idca_agent():
        """
        Retryable callable for IDCA agent execution.
        Creates thread, sends prompt and manuscript, runs agent, validates JSON.
        Returns parsed JSON object.
        """
        # Create a conversation thread
        thread = agents_client.threads.create()

        # Send IDCA instructions
        agents_client.messages.create(
            thread_id=thread.id, role=MessageRole.USER, content=IDCA_PROMPT
        )

        send_in_chunks(thread.id, manuscript)
        msgs = list(agents_client.messages.list(thread_id=thread.id))
        print(f"Messages stored in thread: {len(msgs)}")
        print(f"First chunk:\n{msgs[0].text_messages[0].text.value[:300]}")

        print("\n Running IDCA...\n")

        # Start run
        run = agents_client.runs.create_and_process(
            thread_id=thread.id, agent_id=IDCA_AGENT_ID
        )

        # Retrieve messages after run completes
        message_list = list(agents_client.messages.list(thread_id=thread.id))

        for m in reversed(message_list):
            if m.role == "assistant" and m.text_messages:
                response = m.text_messages[-1].text.value

                # Validate JSON
                import json

                try:
                    idca_json = json.loads(response)
                except:
                    raise RuntimeError("Invalid JSON in IDCA output")

                return {"response": response, "idca_json": idca_json}

        raise RuntimeError("No assistant response returned.")

    # Mark as classifying BEFORE running IDCA
    try:
        entity = table.get_entity("AMIE", request_id)
        entity["status"] = "classifying"
        table.update_entity(entity)
        print(f"\n[STATUS] Set to 'classifying' for request {request_id}")
    except Exception as e:
        print(f"\n[WARNING] Failed to update status to 'classifying': {e}")

    # Execute IDCA agent with retry logic
    result = retry_agent(execute_idca_agent, "IDCA Agent")
    response = result["response"]
    idca_json = result["idca_json"]

    # Save IDCA output to table and mark as classified
    try:
        entity = table.get_entity("AMIE", request_id)
        entity["idca_output"] = response
        entity["status"] = "classified"
        table.update_entity(entity)
        print(f"\n[STATUS] Set to 'classified' for request {request_id}")
    except Exception as e:
        print(f"\n[ERROR] Failed to update status to 'classified': {e}")

    print("\nIDCA Output:\n")
    print(response)

    # -------------------------------
    # CASE 1: NO INVENTION
    # --> Skip NAA completely
    # --> Only run Aggregation Agent
    # -------------------------------
    if idca_json.get("status_determination") != "Present":
        print("\n -------- No invention detected — skipping NAA.")
        print(" -------- Running Aggregation Agent directly...\n")

        try:
            final_report = run_aggregation_agent(
                idca_output=idca_json,
                naa_output=None,  # no NAA outputs
                request_id=request_id,
                table=table,
            )
            # Mark as completed for the UI
            from datetime import datetime

            entity = table.get_entity("AMIE", request_id)
            entity["status"] = "completed"
            entity["completed_at"] = datetime.utcnow().isoformat()
            table.update_entity(entity)
            print(
                f"[STATUS] Set to 'completed' for request {request_id} (No invention)"
            )
        except Exception as e:
            print("\n Aggregation Agent failed:", str(e))

        return response

    if not RUN_NAA:
        # Skip legacy inline NAA; exit after classification
        # But trigger NAA Azure Function if invention is present
        if idca_json.get("status_determination") == "Present":
            try:
                import httpx
                import os

                NAA_BASE = os.getenv("NAA_BASE", "http://localhost:7074/api")
                naa_url = f"{NAA_BASE}/worker/run/{request_id}"
                print(f"\n[TRIGGER] Calling NAA at {naa_url}")
                httpx.post(naa_url, timeout=30.0)
                print(f"[TRIGGER] NAA triggered successfully for {request_id}")
            except Exception as e:
                print(f"\n[ERROR] Failed to trigger NAA: {e}")
        return response

    # -------------------------------
    # CASE 2: INVENTION PRESENT
    # --> Run NAA first
    # --> Then run Aggregation Agent
    # -------------------------------
    # --- NAA pipeline is now a separate Azure Function; skip in local IDCA run ---
    # Trigger NAA Azure Function instead of running inline
    if idca_json.get("status_determination") == "Present":
        try:
            import httpx
            import os

            NAA_BASE = os.getenv("NAA_BASE", "http://localhost:7074/api")
            naa_url = f"{NAA_BASE}/worker/run/{request_id}"
            print(f"\n[TRIGGER] Calling NAA at {naa_url}")
            httpx.post(naa_url, timeout=30.0)
            print(f"[TRIGGER] NAA triggered successfully for {request_id}")
        except Exception as e:
            print(f"\n[ERROR] Failed to trigger NAA: {e}")

    return response  # stop after classification

    try:
        from backend.naa_brain_MVP.naa_test import run_steps_8_to_12

        manuscript_text = get_manuscript_text(request_id)

        print("\n -------- Launching NAA pipeline for request:", request_id)
        naa_outputs = run_steps_8_to_12(manuscript_text, response)

        # Initialize assessments to None (will be populated if RMs are found and assessed)
        assessments = None

        # NEW: Retrieve and Store Reference Manuscripts
        if naa_outputs.lor:
            try:
                import asyncio
                from backend.naa_brain_MVP.rm_retrieval import download_and_store_rms

                print("\n -------- Downloading Reference Manuscripts...")
                asyncio.run(
                    download_and_store_rms(request_id, naa_outputs.lor, blob_service)
                )
            except Exception as e:
                print(f"RM Retrieval Failed: {e}")

            # NEW: Assess RMs if any were downloaded
            try:
                from backend.naa_brain_MVP.rm_assessment import assess_all_rms

                print("\n -------- Assessing Reference Manuscripts against SSR...")

                # SS Synopsis is available in naa_outputs.ss_synopsis
                # SSR is in naa_outputs.ssr

                # Need to run async assessment (reusing loop or new run)
                assessments = asyncio.run(
                    assess_all_rms(
                        request_id,
                        blob_service,
                        naa_outputs.ssr,
                        naa_outputs.ss_synopsis,
                    )
                )

                print("\n===== RM ASSESSMENT RESULTS =====")
                for a in assessments:
                    print(f"\n[Ref] {a.reference_citation}")
                    print(f"      Synopsis: {a.rs_synopsis}")
                    print(
                        f"      Novelty Status: {a.status_determination} (EWSS: {a.sos_score['ewss']})"
                    )

            except Exception as e:
                print(f"RM Assessment Failed: {e}")
                import traceback

                traceback.print_exc()
        # ========================================
        # PERSIST NAA OUTPUT TO TABLE STORAGE
        # ========================================
        try:
            import json
            from datetime import datetime

            # Build lor with assessment data merged with original search results
            lor_with_scores = []

            if assessments and naa_outputs.lor:
                # Create a mapping from filename to assessment
                assessment_map = {a.filename: a for a in assessments}

                # Merge original lor metadata with assessment scores
                for ref in naa_outputs.lor:
                    # Try to find matching assessment by checking if any assessment filename contains the ref title
                    matching_assessment = None
                    for filename, assessment in assessment_map.items():
                        # Simple heuristic: check if title appears in filename
                        if ref.get("title", "").lower()[:20] in filename.lower():
                            matching_assessment = assessment
                            break

                    if matching_assessment:
                        lor_with_scores.append(
                            {
                                "reference_citation": matching_assessment.reference_citation,
                                "rs_synopsis": matching_assessment.rs_synopsis,
                                "sos_score": {
                                    "css": matching_assessment.sos_score.get(
                                        "css", 0.0
                                    ),
                                    "ewss": matching_assessment.sos_score.get(
                                        "ewss", 0.0
                                    ),
                                },
                                "url": ref.get("url", ""),
                                "year": ref.get("year"),
                                "source": ref.get("source", "Unknown"),
                            }
                        )
                    else:
                        # No assessment found, use original lor data only
                        lor_with_scores.append(
                            {
                                "reference_citation": ref.get("title", "Unknown"),
                                "rs_synopsis": "",
                                "sos_score": {"css": 0.0, "ewss": 0.0},
                                "url": ref.get("url", ""),
                                "year": ref.get("year"),
                                "source": ref.get("source", "Unknown"),
                            }
                        )
            elif naa_outputs.lor:
                # No assessments, but we have lor - store search results only
                for ref in naa_outputs.lor:
                    lor_with_scores.append(
                        {
                            "reference_citation": ref.get("title", "Unknown"),
                            "rs_synopsis": "",
                            "sos_score": {"css": 0.0, "ewss": 0.0},
                            "url": ref.get("url", ""),
                            "year": ref.get("year"),
                            "source": ref.get("source", "Unknown"),
                        }
                    )

            # Build naa_output JSON structure
            naa_output_json = {
                "ss_synopsis": naa_outputs.ss_synopsis,
                "source_structure": [
                    block.block_name for block in naa_outputs.ss.blocks
                ]
                if hasattr(naa_outputs.ss, "blocks")
                else [],
                "ssr": {
                    "items": [
                        {
                            "block_name": item.block_name,
                            "weight": item.weight,
                            "match_criteria": item.match_criteria,
                        }
                        for item in naa_outputs.ssr.items
                    ]
                }
                if naa_outputs.ssr
                else {},
                "ucs": naa_outputs.ucs,
                "lor": lor_with_scores,
                "naa_timestamp": datetime.utcnow().isoformat() + "Z",
            }

            # Store in table
            entity = table.get_entity("AMIE", request_id)
            entity["naa_output"] = json.dumps(naa_output_json)
            table.update_entity(entity)

            print(
                f"\n[TABLE STORAGE] NAA output persisted successfully ({len(lor_with_scores)} references)"
            )

        except Exception as e:
            print(f"\n[TABLE STORAGE] Failed to persist NAA output: {e}")
            import traceback

            traceback.print_exc()

        print("\n -------- Running Aggregation Agent...\n")
        try:
            final_report = run_aggregation_agent(
                idca_output=idca_json,
                naa_output=naa_outputs,
                naa_assessments=assessments,  # <--- PASSING THE SCORES
                request_id=request_id,
                table=table,
            )
        except Exception as e:
            print("\n Aggregation Agent failed:", str(e))

    except Exception as e:
        print("\n NAA failed:", str(e))

    return response


# ------------------- CLI -------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run IDCA locally")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--storage", required=True)
    parser.add_argument(
        "--run-naa",
        action="store_true",
        help="Also launch NAA pipeline after classification",
    )
    args = parser.parse_args()

    RUN_NAA = args.run_naa

    request_id = args.request_id
    storage = args.storage

    # Use storage from CLI arg or fall back to env
    storage_conn = storage or AZURE_STORAGE_CONNECTION_STRING
    if not storage_conn:
        raise ValueError(
            " AzureWebJobsStorage missing in .env and --storage not provided"
        )

    # Initialize storage clients with the connection string
    init_storage_clients(storage_conn)

    run_idca(request_id)

    # with No invention detected
    # run_idca("aa9a21b4-3a60-4e45-b0b5-684318ac985e")
    # print("\n")
    # print("SECOND RUNNNNN -----------------------------------")
    # another real STEM manuscript
    # run_idca("d7e98b6f-17fc-421f-afa9-5e4510e34395")
