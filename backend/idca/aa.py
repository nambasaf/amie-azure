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
def build_prompt(idca_output: dict, naa_output, naa_assessments=None):
    citation = idca_output.get("source_citation", "Unknown Citation")
    status = idca_output.get("status_determination")
    justification = idca_output.get("justification", "")
    
    # Get SS Synopsis from NAA output structure if available
    ss_synopsis = getattr(naa_output, "ss_synopsis", "Not available")

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
    # ---------------------------
    
    # 1. HEADER CONTEXT (Step 19)
    # We construct the context header string to pass to the AA
    context_header = f"""
**AMIE Final Results**
*Source Manuscript*: {citation}
*Source Structure*: {ss_synopsis}
"""

    # 2. CHECK FOR DEEP ANALYSIS DATA (Step 18 - Final Reference Table)
    if naa_assessments and len(naa_assessments) > 0:
        # Sort by EWSS desc
        sorted_assessments = sorted(naa_assessments, key=lambda x: x.sos_score['ewss'], reverse=True)
        
        # Build the table: { Citation | RS Synopsis | CSS | EWSS }
        frt_markdown = "| Citation | RS Synopsis | CSS | EWSS |\n|---|---|---|---|\n"
        
        for a in sorted_assessments:
            # Format scores
            css = a.sos_score.get('css', 0)
            ewss = a.sos_score.get('ewss', 0)
            
            # Clean text for table
            cit = a.reference_citation.replace("\n", " ")[:100] + "..." if len(a.reference_citation) > 100 else a.reference_citation
            syn = a.rs_synopsis.replace("\n", " ")
            
            frt_markdown += f"| {cit} | {syn} | {css} | {ewss} |\n"

        return f"""
{context_header}

INSTRUCTIONS FOR FINAL REPORT:
1. You are the Aggregation Agent (AA).
2. Your goal is to display the Final Reference Table (FRT) exactly as provided below.
3. Keep the Context Header above the table.
4. Do NOT add any "Provisional" analysis or "Search Results" sections. Use the DEEP ANALYSIS data provided.

DATA TO DISPLAY:

{frt_markdown}

"""

    # ---------------------------
    # CASE C — Fallback (No Assessments)
    # ---------------------------
    lor = getattr(naa_output, "lor", [])
    if not lor:
         return f"""
IDCA Output:
Status: {status}
Citation: {citation}

NAA Output Summary:
NAA produced Source Structure, SSR, SS Synopsis, and UCS.
Parallel Search logic was executed but returned NO references.

Please produce the novelty decision for the MVP:
- Because no reference manuscripts were found, conclude the manuscript is provisionally NOVEL.
- Do NOT display SS, SSR, UCS, or NAA blocks in the final report.
"""

    # Fallback to search results if assessments failed
    ref_table = "| Source | Year | Title | URL |\n|---|---|---|---|\n"
    for r in lor[:10]:
        ref_table += f"| {r.get('source')} | {r.get('year')} | {r.get('title')} | {r.get('url')} |\n"

    return f"""
IDCA Output:
Status: {status}
Citation: {citation}

NAA Output Summary:
NAA produced Source Structure, SSR, SS Synopsis, and UCS.

PRIOR ART SEARCH RESULTS (No Deep Analysis available):
The Progressive Parallel Search Engine found the following relevant references:

{ref_table}

INSTRUCTIONS FOR FINAL REPORT:
1. Display the "Reference Manuscripts Sorted By Relevance" list (using the table above).
2. Provide a "Provisional Similarity Assessment" based on titles/abstracts.
3. Conclude with a provisional novelty statement.
"""


# -------------------------------------------------------------
# MAIN FUNCTION CALLED BY IDCA
# -------------------------------------------------------------
def run_aggregation_agent(idca_output: dict, naa_output, naa_assessments=None):
    prompt = build_prompt(idca_output, naa_output, naa_assessments)
    final_report = _run_aa(prompt)

    print("\n===== AGGREGATION AGENT FINAL REPORT =====\n")
    print(final_report)
    print("\n==========================================\n")

    return final_report


