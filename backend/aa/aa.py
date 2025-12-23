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

from backend.utils.retry import retry_agent

# ------------------------------------------------------------------
# ENVIRONMENT
# ------------------------------------------------------------------
load_dotenv()

PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT")
AGGREGATION_AGENT_ID = os.getenv("AGGREGATION_AGENT_ID")

if not PROJECT_ENDPOINT:
    raise ValueError("PROJECT_ENDPOINT missing in environment")
if not AGGREGATION_AGENT_ID:
    raise ValueError("AGGREGATION_AGENT_ID missing in environment")

# ------------------------------------------------------------------
# AZURE CLIENT
# ------------------------------------------------------------------
agents_client = AgentsClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(
        exclude_environment_credential=True,
        exclude_managed_identity_credential=True,
    ),
)

# ------------------------------------------------------------------
# HELPER – RUN AGENT ONCE
# ------------------------------------------------------------------


def _run_aa(prompt: str) -> str:
    """Creates a thread, sends user prompt, runs AA, returns final reply text."""
    thread = agents_client.threads.create()

    agents_client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=prompt,
    )

    agents_client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=AGGREGATION_AGENT_ID,
    )

    msgs = list(agents_client.messages.list(thread_id=thread.id))
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
    status = idca_output.get("status_determination")
    justification = idca_output.get("justification", "")

    ss_synopsis = getattr(naa_output, "ss_synopsis", "Not available")

    # ---------------- CASE A – No Invention Present ----------------
    if status != "Present":
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
        sorted_assess = sorted(
            naa_assessments, key=lambda a: a.sos_score["ewss"], reverse=True
        )
        frt_md = "| Citation | RS Synopsis | CSS | EWSS |\n|---|---|---|---|\n"
        for a in sorted_assess:
            css = a.sos_score.get("css", 0)
            ewss = a.sos_score.get("ewss", 0)
            cit = (
                a.reference_citation.replace("\n", " ")[:100] + "..."
                if len(a.reference_citation) > 100
                else a.reference_citation
            )
            syn = a.rs_synopsis.replace("\n", " ")
            frt_md += f"| {cit} | {syn} | {css} | {ewss} |\n"

        return f"""
{context_header}

INSTRUCTIONS FOR FINAL REPORT:
1. You are the Aggregation Agent (AA).
2. Display the Final Reference Table (FRT) exactly as provided below.
3. Keep the Context Header above the table.
4. Do NOT add any extra sections beyond the FRT.

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
