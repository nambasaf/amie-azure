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
# PROMPT BUILDER (SSOW-STRICT)
# ------------------------------------------------------------------
def build_prompt(
    idca_output: dict[str, Any],
    naa_output: Any,
    naa_assessments: Optional[List[dict]] = None,
) -> str:
    """Builds a STRICT SSOW prompt for the Aggregation Agent."""

    citation = idca_output.get("source_citation", "Unknown Citation")
    status = idca_output.get("status_determination", "").strip().lower()
    idca_output["status_determination"] = (
        "Present" if status == "present" else idca_output.get("status_determination")
    )

    print(
    f"[AA DEBUG] CASE CHECK -> status={idca_output.get('status_determination')}, "
    f"assessments={len(naa_assessments or [])}"
)


    justification = idca_output.get("justification", "")

    ss_synopsis = getattr(naa_output, "ss_synopsis", "Not available")

    # ------------------------------------------------------------
    # CASE A — NO INVENTION PRESENT
    # ------------------------------------------------------------
    if status != "Present":
        return f"""
**AMIE Final Results**

*Source Manuscript*: {citation}

IDCA Determination:
No invention present.

Justification:
{justification}
"""

    # ------------------------------------------------------------
    # CASE B — INVENTION PRESENT, BUT NO ASSESSMENTS
    # ------------------------------------------------------------
    if not naa_assessments:
        return f"""
**AMIE Final Results**

*Source Manuscript*: {citation}
*Source Structure*: {ss_synopsis}

Novelty cannot be determined due to missing structural assessment data.
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
    """Executes AA prompt with retries and persists output if requested."""

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
