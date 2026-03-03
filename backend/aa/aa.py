# -------------------------------------------------------------
# AGGREGATION AGENT (AA) – SSOW-STRICT PRODUCTION VERSION
# -------------------------------------------------------------
"""
Aggregation Agent logic implementing SSOW Steps 18–19.

This agent acts as a NOVELTY ADJUDICATOR.
It relies exclusively on NAA structural assessments (CSS / EWSS).

Public entrypoint:
    run_aggregation_agent(idca_output, naa_output, naa_assessments, ...)
"""

from __future__ import annotations

import os
from typing import Any, Optional, List

from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import MessageRole
from azure.identity import DefaultAzureCredential

try:
    from retry import retry_agent
except ImportError:
    # If imported from within the backend package (e.g. by idca.py)
    from backend.aa.retry import retry_agent

# ------------------------------------------------------------------
# LAZY AZURE CLIENT & ENV VALIDATION
# ------------------------------------------------------------------
_agents_client = None

def get_agents_client():
    global _agents_client
    if _agents_client is not None:
        return _agents_client

    load_dotenv()
    
    endpoint = os.getenv("PROJECT_ENDPOINT")
    if not endpoint:
        # In Azure, these should be set in App Settings
        raise ValueError("Environment variable 'PROJECT_ENDPOINT' is missing. Please set it in Azure App Settings or .env")

    from azure.ai.agents import AgentsClient

    _agents_client = AgentsClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )
    return _agents_client


def get_agent_id(var_name: str) -> str:
    agent_id = os.getenv(var_name)
    if not agent_id:
        raise ValueError(f"Environment variable '{var_name}' is missing. Please set it in Azure App Settings or .env")
    return agent_id


# ------------------------------------------------------------------
# HELPER – RUN AGENT ONCE
# ------------------------------------------------------------------
def _run_aa(prompt: str) -> str:
    """Creates a thread, sends user prompt, runs AA, returns final reply text."""
    client = get_agents_client()
    agent_id = get_agent_id("AGGREGATION_AGENT_ID")
    
    thread = client.threads.create()

    client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=prompt,
    )

    client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent_id,
    )

    msgs = list(client.messages.list(thread_id=thread.id))
    for m in reversed(msgs):
        if m.role == "assistant" and m.text_messages:
            return m.text_messages[-1].text.value.strip()

    raise RuntimeError("Aggregation Agent returned no assistant output")

# ------------------------------------------------------------------
# PROMPT BUILDER (SSOW-STRICT)
# ------------------------------------------------------------------
def build_prompt(
    idca_output: dict[str, Any],
    naa_output: Any,
    naa_assessments: Optional[List[dict]] = None,
) -> str:
    """Builds a STRICT SSOW prompt for the Aggregation Agent."""

    citation = idca_output.get("source_citation", "Unknown Citation")
    status = (idca_output.get("status_determination") or "").strip().lower()
    justification = idca_output.get("justification", "")

    ss_synopsis = getattr(naa_output, "ss_synopsis", "Not available")

    # ---------------- CASE A – No Invention Present ----------------
    if status != "present":
        return f"""
**AMIE Final Results**

*Source Manuscript*: {citation}

IDCA Determination:
No invention present.

Justification:
{justification}
"""

    # ---------------- CASE B – Invention Present ----------------
    context_header = f"**AMIE Final Results**\n*Source Manuscript*: {citation}\n*Source Structure*: {ss_synopsis}\n"

    # ------------ Deep-analysis path (assessments present) --------
    if naa_assessments:
        # Helper to handle both object (attribute) and dict (item) access
        def get_val(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        sorted_assess = sorted(
            naa_assessments, 
            key=lambda a: get_val(a, "sos_score", {}).get("ewss", 0), 
            reverse=True
        )
        frt_md = "| Citation | RS Synopsis | CSS | EWSS |\n|---|---|---|---|\n"
        for a in sorted_assess:
            score = get_val(a, "sos_score", {})
            css = score.get("css", 0)
            ewss = score.get("ewss", 0)
            
            raw_cit = get_val(a, "reference_citation", "Unknown")
            cit = (
                raw_cit.replace("\n", " ")[:100] + "..."
                if len(raw_cit) > 100
                else raw_cit
            )
            syn = get_val(a, "rs_synopsis", "Not available").replace("\n", " ")
            frt_md += f"| {cit} | {syn} | {css} | {ewss} |\n"

        return f"""
{context_header}

INSTRUCTIONS FOR FINAL REPORT:
1. You are the Aggregation Agent (AA).
2. Display the Final Reference Table (FRT) exactly as provided below.
3. Keep the Context Header above the table.
4. AFTER the table, you MUST include a section titled "**Novelty Verdict**".
5. The Novelty Verdict MUST be one of:
   - NOVEL
   - NOT NOVEL
   - INCONCLUSIVE
6. Do NOT use hedging language ("may", "appears", "potentially") in the verdict line.
7. After the verdict line, include a short **Rationale** (2–4 sentences) that
   justifies the verdict using CSS/EWSS comparisons.

DATA TO DISPLAY:\n\n{frt_md}
"""

    # ------------------------------------------------------------
    # CASE C — INVENTION PRESENT + STRUCTURAL ASSESSMENTS
    # ------------------------------------------------------------
    # Sort by EWSS descending
    sorted_assessments = sorted(
        naa_assessments,
        key=lambda a: a["scores"]["ewss"],
        reverse=True,
    )

    # Build Final Reference Table (FRT)
    frt_md = "| Citation | RS Synopsis | CSS | EWSS |\n"
    frt_md += "|---|---|---|---|\n"

    for a in sorted_assessments:
        frt_md += (
            f"| {a['reference_citation']} "
            f"| {a['rs_synopsis']} "
            f"| {a['scores'].get('css', 0):.2f} "
            f"| {a['scores'].get('ewss', 0):.2f} |\n"
        )

    # Deterministic novelty rule
    max_ewss = sorted_assessments[0]["scores"]["ewss"]

    if max_ewss >= 0.90:
        determination = "NOT NOVEL"
        cause_refs = [
            a["reference_citation"]
            for a in sorted_assessments
            if a["scores"]["ewss"] >= 0.90
        ]
    else:
        determination = "NOVEL"
        cause_refs = []

    cause_text = (
        "This determination is based on high structural overlap (EWSS ≥ 0.90) with:\n- "
        + "\n- ".join(cause_refs)
        if cause_refs
        else f"The highest observed EWSS was {max_ewss:.2f}, below the anticipation threshold."
    )

    return f"""
**AMIE Final Results**

*Source Manuscript*: {citation}
*Source Structure*: {ss_synopsis}

### Final Reference Table (Structural Comparisons)
{frt_md}

### Novelty Determination
This manuscript is **{determination}**.

{cause_text}
"""

# ------------------------------------------------------------------
# PUBLIC API
# ------------------------------------------------------------------
def run_aggregation_agent(
    idca_output: dict[str, Any],
    naa_output: Any,
    naa_assessments: Optional[List[dict]] = None,
    *,
    request_id: str | None = None,
    table=None,
) -> str:
    """Executes AA prompt with retries and persists to Table if provided."""

    if naa_assessments is None:
        raise ValueError("AA called with naa_assessments=None — invalid pipeline state")

    prompt = build_prompt(idca_output, naa_output, naa_assessments)

    final_report = retry_agent(lambda: _run_aa(prompt), "Aggregation Agent")

    if request_id and table:
        try:
            entity = table.get_entity("AMIE", request_id)
            entity["aa_output"] = final_report
            table.update_entity(entity)
        except Exception as exc:
            print(f"[TABLE] Failed to persist AA output: {exc}")

    return final_report
