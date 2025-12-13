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
from aa import run_aggregation_agent



# Load .env variables
load_dotenv()

# ------------------- ENV -------------------
PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT")
MODEL_DEPLOYMENT = os.getenv("MODEL_DEPLOYMENT")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AzureWebJobsStorage")

if not PROJECT_ENDPOINT:
    raise ValueError(" PROJECT_ENDPOINT missing in .env")

if not MODEL_DEPLOYMENT:
    raise ValueError(" MODEL_DEPLOYMENT missing in .env")

if not AZURE_STORAGE_CONNECTION_STRING:
    raise ValueError(" AzureWebJobsStorage missing in .env")

CONTAINER_NAME = "manuscript-uploads"
TABLE_NAME = "IngestionRequests"

# ------------------- Azure Clients -------------------
agents_client = AgentsClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(
        exclude_environment_credential=True,
        exclude_managed_identity_credential=True
    ),
)

blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
table_service = TableServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

container = blob_service.get_container_client(CONTAINER_NAME)
table = table_service.get_table_client(TABLE_NAME)

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
            thread_id=thread_id,
            role=MessageRole.USER,
            content=text[i:i+chunk_size]
        )

# ------------------- Run IDCA -------------------
def run_idca(request_id: str):
    manuscript = get_manuscript_text(request_id)
    print("\n--- MANUSCRIPT SIZE:", len(manuscript), "characters ---\n")

    # Create a conversation thread
    thread = agents_client.threads.create()

     # Send IDCA instructions
    agents_client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=IDCA_PROMPT
    )

    send_in_chunks(thread.id, manuscript)
    msgs = list(agents_client.messages.list(thread_id=thread.id))
    print(f"Messages stored in thread: {len(msgs)}")
    print(f"First chunk:\n{msgs[0].text_messages[0].text.value[:300]}")

    print("\n Running IDCA...\n")

    # Start run
    run = agents_client.runs.create_and_process(
    thread_id=thread.id,
    agent_id=IDCA_AGENT_ID
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

            # Save IDCA output to table
            entity = table.get_entity("AMIE", request_id)
            entity["idca_output"] = response
            entity["status"] = "classified"
            table.update_entity(entity)

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
                        naa_output=None        # no NAA outputs
                    )
                except Exception as e:
                    print("\n Aggregation Agent failed:", str(e))

                return response

            # -------------------------------
            # CASE 2: INVENTION PRESENT
            # --> Run NAA first
            # --> Then run Aggregation Agent
            # -------------------------------
            try:
                from naa_brain_MVP.naa_test import run_steps_8_to_12
                manuscript_text = get_manuscript_text(request_id)

                print("\n -------- Launching NAA pipeline for request:", request_id)
                naa_outputs = run_steps_8_to_12(manuscript_text, response)

                print("\n -------- Running Aggregation Agent...\n")
                try:
                    final_report = run_aggregation_agent(
                        idca_output=idca_json,
                        naa_output=naa_outputs
                    )
                except Exception as e:
                    print("\n Aggregation Agent failed:", str(e))

            except Exception as e:
                print("\n NAA failed:", str(e))

            return response

    raise RuntimeError("No assistant response returned.")



# ------------------- CLI -------------------
if __name__ == "__main__":
    
    run_idca("1d235a2f-f03c-4f71-ae92-a5f61de38d29")

    # with No invention detected 
    # run_idca("aa9a21b4-3a60-4e45-b0b5-684318ac985e")
