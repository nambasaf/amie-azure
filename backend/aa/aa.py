# -------------------------------------------------------------
# AGGREGATION AGENT (AA) – production version moved from idca/aa.py
# -------------------------------------------------------------
"""Aggregation Agent logic implementing SSOW Steps 18–19.

This module exposes a single public function:
    run_aggregation_agent(idca_output: dict, naa_output, naa_assessments=None,
                          request_id: str | None = None, table=None) -> str

It constructs the AA prompt according to the workflow and executes an Azure
AI Agent (using `AGGREGATION_AGENT_ID`).  If a Table Storage client and
request-id are provided it will persist the AA output.
"""

from __future__ import annotations

import os
import json
from typing import Any, Optional

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
# PROMPT BUILDER (covers SSOW logic)
# ------------------------------------------------------------------


def build_prompt(
    idca_output: dict[str, Any],
    naa_output: Any,
    naa_assessments: Optional[list[Any]] = None,
) -> str:
    """Returns the final prompt string to feed to the Aggregation Agent."""
    citation = idca_output.get("source_citation", "Unknown Citation")
    status = (idca_output.get("status_determination") or "").strip().lower()
    justification = idca_output.get("justification", "")

    ss_synopsis = getattr(naa_output, "ss_synopsis", "Not available")

    # ---------------- CASE A – No Invention Present ----------------
    if status != "present":
        return f"""
IDCA Output:
Status: {status}
Citation: {citation}
Justification: {justification}

No NAA output.

Please produce the 'No Invention Present' final report.
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

    # ------------ Fallback paths (no assessments) -----------------
    lor = getattr(naa_output, "lor", [])
    if not lor:
        return f"""
IDCA Output:
Status: {status}
Citation: {citation}

NAA Output Summary:
NAA produced Source Structure, SSR, SS Synopsis, and UCS.
Parallel search produced NO reference manuscripts.

Please conclude the manuscript is provisionally NOVEL. Do NOT display SS/SSR/UCS blocks.
"""

    # Search results available but no deep analysis
    ref_table = "| Source | Year | Title | URL |\n|---|---|---|---|\n"
    for r in lor[:10]:
        ref_table += f"| {r.get('source')} | {r.get('publication_date', '')[:4]} | {r.get('title')} | {r.get('url', '')} |\n"

    return f"""
IDCA Output:
Status: {status}
Citation: {citation}

NAA Output Summary:
Source Structure, SSR, SS Synopsis, UCS all generated.

PRIOR ART SEARCH RESULTS (No Deep Analysis):\n\n{ref_table}

INSTRUCTIONS FOR FINAL REPORT:
1. Display the Table above.
2. Provide a short novelty assessment based on the titles/abstracts.
"""


# ------------------------------------------------------------------
# PUBLIC API
# ------------------------------------------------------------------


def run_aggregation_agent(
    idca_output: dict[str, Any],
    naa_output: Any,
    naa_assessments: Optional[list[Any]] = None,
    *,
    request_id: str | None = None,
    table=None,
) -> str:
    """Executes AA prompt with retries and persists to Table if provided."""

    if naa_assessments is None:
        raise ValueError("AA called with naa_assessments=None — invalid pipeline state")

    prompt = build_prompt(idca_output, naa_output, naa_assessments)

    def _exec():
        return _run_aa(prompt)

    final_report = retry_agent(_exec, "Aggregation Agent")

    if request_id and table:
        try:
            entity = table.get_entity("AMIE", request_id)
            entity["aa_output"] = final_report
            table.update_entity(entity)
            print(f"[TABLE] AA output stored for {request_id}")
        except Exception as exc:
            print(f"[TABLE] Failed to persist AA output: {exc}")

    return final_report
