import os
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

Your task is to analyze a Source Manuscript (SM) and determine whether it discloses a concrete and useful Source Technology (ST).

Follow these rules strictly:

1. Assess whether the SM describes a buildable, operational technology.
2. If it describes only background theory, ideas, or speculation, return status_determination = "Absent" or "Implied".
3. If the technology is clearly described, return status_determination = "Present".
4. Generate an APA-style citation for the manuscript.
5. If status_determination = "Present", list the scientific or engineering domains required to understand the technology (Fields Map).
6. Return output **ONLY** in the following JSON format:

{

  "status_determination": "Present | Implied | Absent",
  "justification": "Short explanation supporting the determination.",
  "source_citation": "APA formatted citation for the manuscript.",
  "fields_map": [
    "Field 1",
    "Field 2",
    "Field 3"
  ],

  "structural_synopsis": "1–3 sentence summary of the technology (only if Present)."
}

"""

# Create the IDCA agent
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
            print("\n IDCA Output:\n")
            print(response)
            print("\n---------------------------------------\n")
            return response

    raise RuntimeError(" No assistant response returned.")


# ------------------- CLI -------------------
if __name__ == "__main__":
    print("Enter a request_id from your uploaded manuscripts:")
    request_id = input("> ").strip()
    run_idca(request_id)
