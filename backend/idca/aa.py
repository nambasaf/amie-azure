# -------------------------------------------------------------
# THIS FILE IS A STUB FOR THE AGGREGATION AGENT
# -------------------------------------------------------------
import os
import json
from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import MessageRole
from azure.identity import DefaultAzureCredential

load_dotenv()

# ------------------- ENV -------------------
PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT")
AGGREGATION_AGENT_ID = os.getenv("AGGREGATION_AGENT_ID")   # <-- Ensure this matches .env

if not PROJECT_ENDPOINT:
    raise ValueError("PROJECT_ENDPOINT missing in .env")

if not AGGREGATION_AGENT_ID:
    raise ValueError("AGGREGATION_AGENT_ID missing in .env")

# ------------------- Azure Client -------------------
agents_client = AgentsClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(
        exclude_environment_credential=True,
        exclude_managed_identity_credential=True
    ),
)

# -------------------------------------------------------------
# Wrapper to run the AA agent
# -------------------------------------------------------------
def _run_aa(prompt: str) -> str:
    """Runs the Aggregation Agent and returns its final response."""
    thread = agents_client.threads.create()

    agents_client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=prompt
    )

    agents_client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=AGGREGATION_AGENT_ID
    )

    msgs = list(agents_client.messages.list(thread_id=thread.id))
    for msg in reversed(msgs):
        if msg.role == "assistant" and msg.text_messages:
            return msg.text_messages[-1].text.value.strip()

    raise RuntimeError("Aggregation Agent returned no output.")

# -------------------------------------------------------------
# Prompt Builder (MVP logic)
# -------------------------------------------------------------
def build_prompt(idca_output: dict, naa_output):
    citation = idca_output.get("source_citation", "Unknown Citation")
    status = idca_output.get("status_determination")
    justification = idca_output.get("justification", "")

    # ---------------------------
    # CASE A — No Invention Present
    # ---------------------------
    if status != "Present":
        return f"""
IDCA Output:
Status: {status}
Citation: {citation}
Justification: {justification}

No NAA output.

Please produce the 'No Invention Present' final report.
"""

    # ---------------------------
    # CASE B — Invention Present
    # (MVP: no reference manuscripts yet)
    # ---------------------------
    return f"""
IDCA Output:
Status: {status}
Citation: {citation}

NAA Output Summary:
NAA produced Source Structure, SSR, SS Synopsis, and UCS.
Reference Manuscripts list is empty because Steps 12–17 are not implemented yet.

Please produce the novelty decision for the MVP:
- Because no reference manuscripts were found, conclude the manuscript is provisionally NOVEL.
- Do NOT display SS, SSR, UCS, or NAA blocks in the final report.
"""


# -------------------------------------------------------------
# MAIN FUNCTION CALLED BY IDCA
# -------------------------------------------------------------
def run_aggregation_agent(idca_output: dict, naa_output):
    prompt = build_prompt(idca_output, naa_output)
    final_report = _run_aa(prompt)

    print("\n===== AGGREGATION AGENT FINAL REPORT =====\n")
    print(final_report)
    print("\n==========================================\n")

    return final_report


