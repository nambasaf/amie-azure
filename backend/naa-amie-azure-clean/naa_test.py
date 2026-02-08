import os
import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any

from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import MessageRole
from azure.identity import DefaultAzureCredential

# ---------------------------------------------------------------------
# LAZY AZURE CLIENT & ENV VALIDATION
# ---------------------------------------------------------------------
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

    from azure.identity import DefaultAzureCredential
    from azure.ai.agents import AgentsClient

    _agents_client = AgentsClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(
            exclude_environment_credential=True,
            exclude_managed_identity_credential=True,
        ),
    )
    return _agents_client


def get_agent_id(var_name: str) -> str:
    agent_id = os.getenv(var_name)
    if not agent_id:
        raise ValueError(f"Environment variable '{var_name}' is missing. Please set it in Azure App Settings or .env")
    return agent_id

# Backward compatibility for modules that import these at top-level
SS_AGENT_ID = os.getenv("SS_Agent_ID")
SSR_AGENT_ID = os.getenv("SSR_Agent_ID")
SS_SYNOPSIS_AGENT_ID = os.getenv("SS_Synopsis_Agent_ID")
UCS_BUILDER_AGENT_ID = os.getenv("UCS_Builder_Agent_ID")


# ---------------------------------------------------------------------
# CHAT WRAPPER – SIMPLE & SAFE
# ---------------------------------------------------------------------
def _chat(agent_id: str, prompt: str) -> str:
    """
    Runs a specific NAA step agent.

    - Creates a thread
    - Sends a single user message with `prompt`
    - Runs the agent
    - Returns the final assistant reply text (stripped)
    """
    # 1. Get client and validate environment lazily
    client = get_agents_client()

    # 1. Create thread
    thread = client.threads.create()

    # 2. Send user message
    client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,  # only user/assistant are allowed
        content=prompt,
    )

    # 3. Run agent
    _ = client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent_id,
    )

    # 4. Collect assistant response
    msgs = list(client.messages.list(thread_id=thread.id))
    for msg in reversed(msgs):
        if msg.role == "assistant" and msg.text_messages:
            text = msg.text_messages[-1].text.value.strip()
            if not text:
                raise RuntimeError(f"Agent {agent_id} returned an empty response.")

            # Strip markdown code fences if they appear

            if text.startswith("```"):
                # Remove leading/trailing ```
                text = text.strip("`").strip()

                # Remove language identifier if present (json, yaml, etc.)
                for lang in ("json", "yaml", "js", "python"):
                    if text.lower().startswith(lang):
                        text = text[len(lang) :].strip()

            # Final sanity: ensure clean JSON starts correctly if JSON expected
            text = text.strip()

            return text

    raise RuntimeError(f"No assistant output returned for agent {agent_id}.")


from retry import retry_agent


# ---------------------------------------------------------------------
# DATA MODELS
# ---------------------------------------------------------------------
@dataclass
class SSBlock:
    block_name: str
    function: str
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)


@dataclass
class SourceStructure:
    blocks: List[SSBlock]


@dataclass
class SSRItem:
    block_name: str
    weight: float
    match_criteria: str
    notes: str = ""


@dataclass
class StructuralScoringRubric:
    items: List[SSRItem]


@dataclass
class NAAOutputs:
    ss: SourceStructure
    ssr: StructuralScoringRubric
    ss_synopsis: str
    ucs: str
    lor: List[Dict[str, Any]] = field(default_factory=list)  # [NEW] Add LoR field


# ---------------------------------------------------------------------
# STEP 8 — SOURCE STRUCTURE (SS)
# ---------------------------------------------------------------------
def build_source_structure(manuscript_text: str, idca_output: str, agent_id: str) -> SourceStructure:
    prompt = f"""
Decompose the Source Technology into elemental structural blocks.

Each block MUST include:
- block_name
- function
- inputs
- outputs
- assumptions (if any)

Return ONLY this JSON:

{{
  "source_structure": [
    {{
      "block_name": "...",
      "function": "...",
      "inputs": ["..."],
      "outputs": ["..."],
      "assumptions": ["..."]
    }}
  ]
}}

Source Manuscript:
{manuscript_text[:8000]}

IDCA Output:
{idca_output}
"""

    raw = _chat(agent_id, prompt)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Step 8 (SS) agent did not return valid JSON. Raw output:\n{raw}"
        ) from e

    if "source_structure" not in data:
        raise RuntimeError(
            f"JSON from SS agent missing 'source_structure' key. Got:\n{data}"
        )

    blocks = []
    for b in data["source_structure"]:
        blocks.append(
            SSBlock(
                block_name=b["block_name"],
                function=b["function"],
                inputs=b.get("inputs", []),
                outputs=b.get("outputs", []),
                assumptions=b.get("assumptions", []),
            )
        )

    return SourceStructure(blocks=blocks)


# ---------------------------------------------------------------------
# STEP 9 — STRUCTURAL SCORING RUBRIC (SSR)
# ---------------------------------------------------------------------
def build_ssr(ss: SourceStructure, agent_id: str) -> StructuralScoringRubric:
    summary = "\n".join(f"- {b.block_name}: {b.function}" for b in ss.blocks)

    prompt = f"""
You are constructing a Structural Scoring Rubric (SSR) for the Source Structure (SS).

The purpose of the SSR is to evaluate whether a Reference Manuscript discloses
the same structural elements as the Source Structure – NOT how well they perform.

STRICT RULES (must be followed):
- The SSR measures structural overlap only.
- DO NOT include performance metrics, efficiencies, capacities, cycle life, timing values, or numerical thresholds.
- DO NOT impose implementation details, engineering specifications, or optimization targets.
- DO NOT reflect quality, size, maturity, or performance of any subsystem.

Each SSR entry must define:
- block_name (exact SS block name)
- weight (0–1 reflecting relative importance within the architecture)
- match_criteria (what must be present in a Reference Manuscript to count as a structural match)
- notes (clarify structural role, NOT performance characteristics)

The SSR determines whether a Reference Structure (RS) contains the same
building blocks as the Source Structure. It does NOT judge performance.

Return ONLY this JSON:
{{
  "ssr": [
    {{
      "block_name": "...",
      "weight": 0.5,
      "match_criteria": "...",
      "notes": "...",
    }}
  ]
}}

Source Structure:
{summary}
"""

    raw = _chat(agent_id, prompt)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Step 9 (SSR) agent did not return valid JSON. Raw output:\n{raw}"
        ) from e

    if "ssr" not in data:
        raise RuntimeError(f"JSON from SSR agent missing 'ssr' key. Got:\n{data}")

    items = []
    for r in data["ssr"]:
        items.append(
            SSRItem(
                block_name=r["block_name"],
                weight=float(r["weight"]),
                match_criteria=r["match_criteria"],
                notes=r.get("notes", ""),
            )
        )

    return StructuralScoringRubric(items=items)


# ------ function to help change the results from ssr to a table format ------
def render_ssr_table(ssr: StructuralScoringRubric) -> str:
    """Render the SSR as a formatted markdown table for human inspection."""
    header = "| SS Block | Weight | Match Criteria | Notes |\n"
    divider = "|---------|--------|---------------|-------|\n"
    rows = ""

    for item in ssr.items:
        rows += (
            f"| {item.block_name} "
            f"| {item.weight} "
            f"| {item.match_criteria} "
            f"| {item.notes} |\n"
        )

    return header + divider + rows


# ---------------------------------------------------------------------
# STEP 10 — SS SYNOPSIS (ONE SENTENCE)
# ---------------------------------------------------------------------
def ss_synopsis(ss: SourceStructure, agent_id: str) -> str:
    summary = "\n".join(f"- {b.block_name}: {b.function}" for b in ss.blocks)

    prompt = f"""
Write a ONE-SENTENCE structural synopsis of the SS.

Rules:
- actor → operation → object/outcome
- present tense
- no citations, no hedges, no benefits
- only use SS terms

SS Blocks:
{summary}

Return ONLY the sentence.
"""

    out = _chat(agent_id, prompt)
    return out.strip()


# ---------------------------------------------------------------------
# STEP 11 — UNIFIED COMPOSITE SEARCH STRING (UCS)
# ---------------------------------------------------------------------
def build_ucs(ss: SourceStructure, agent_id: str) -> str:
    summary = "\n".join(f"- {b.block_name}: {b.function}" for b in ss.blocks)

    prompt = f"""
Convert the SS into a Unified Composite Search string (UCS).

STRICT REQUIREMENTS (must be followed exactly):

1. Each SS block MUST become a separate semantic constraint.
2. Constraints MUST be combined using top-level AND operators.
3. Within each constraint, use OR only for synonyms or equivalent phrases.
4. Do NOT collapse multiple SS blocks into a single OR chain.
5. Do NOT use OR at the top level of the query.
6. Proximity operators (e.g., NEAR/n) may be used ONLY inside a single block.
7. Parentheses MUST be used so that each block is clearly separable.
8. Output must be ONE line only.

The resulting UCS MUST have this structure:

(Block 1 synonyms) AND (Block 2 synonyms) AND (Block 3 synonyms) AND ...

This AND-separated block structure is REQUIRED for downstream ablation logic.

SS Blocks:
{summary}

Return ONLY the UCS string.
"""

    ucs = _chat(agent_id, prompt)
    # normalize whitespace
    return " ".join(ucs.split())


# ---------------------------------------------------------------------
# PIPELINE ORCHESTRATOR (8–11)
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# PIPELINE ORCHESTRATOR (8–11)
# ---------------------------------------------------------------------
async def run_steps_8_to_12(manuscript_text: str, idca_output: str) -> NAAOutputs:
    logging.info("Starting NAA workflow...\n")

    # -------------------- STEP 8 --------------------
    logging.info("\n===== SOURCE STRUCTURE (SS) =====")
    ss_id = get_agent_id("SS_Agent_ID")
    ss = retry_agent(
        lambda: build_source_structure(manuscript_text, idca_output, ss_id), "SS Agent"
    )
    logging.info(" [SS AGENT OUTPUT]")
    for blk in ss.blocks:
        logging.info(f"  {blk}")
    logging.info("\n")

    # -------------------- STEP 9 --------------------
    logging.info("\n [SSR AGENT] Building Structural Scoring Rubric...")
    ssr_id = get_agent_id("SSR_Agent_ID")
    ssr = retry_agent(lambda: build_ssr(ss, ssr_id), "SSR Agent")
    logging.info("[SSR AGENT OUTPUT]")
    for item in ssr.items:
        logging.info(f"  {item}")
    logging.info("\n")

    logging.info("\n[SSR TABLE]")
    logging.info(render_ssr_table(ssr))
    logging.info("\n")

    # -------------------- STEP 10 --------------------
    logging.info("\n[SS SYNOPSIS AGENT] Creating Source Structure Synopsis...")
    synopsis_id = get_agent_id("SS_Synopsis_Agent_ID")
    synopsis = retry_agent(lambda: ss_synopsis(ss, synopsis_id), "SS Synopsis Agent")
    logging.info(" [SS SYNOPSIS OUTPUT]")
    logging.info(f"  {synopsis}")
    logging.info("\n")

    # -------------------- STEP 11 --------------------
    logging.info("\n [UCS AGENT] Generating Unified Composite Search String...")
    ucs_id = get_agent_id("UCS_Builder_Agent_ID")
    ucs = retry_agent(lambda: build_ucs(ss, ucs_id), "UCS Agent")
    logging.info("[UCS OUTPUT]")
    logging.info(f"  {ucs}")
    logging.info("\n")

    # -------------------- STEP 12 --------------------
    logging.info(
        "\n [PRIOR ART SEARCH] Executing PARALLEL PROGRESSIVE SEARCH (OpenAlex + PatentsView + Semantic Scholar)..."
    )

    # Fallback: if UCS is empty or too short, use SS synopsis or manuscript excerpt so search still runs
    search_query = (ucs or "").strip()
    if len(search_query) < 20:
        search_query = (synopsis or "").strip()[:500] or (manuscript_text or "")[:500].strip()
        if search_query:
            logging.info(f"UCS empty/short — using fallback query ({len(search_query)} chars) for prior-art search")
        else:
            search_query = "prior art"  # last resort
            logging.warning("UCS and fallback empty — using minimal query 'prior art'")

    from search_orchestrator import (
        progressive_search as parallel_progressive_search,
    )

    try:
        # Run async search directly
        final_query, LoR = await parallel_progressive_search(search_query, target_total=5)

        logging.info("\n[STEP 12 OUTPUT]")
        logging.info(f" PRIOR ART QUERY: {final_query if final_query else '(none)'}")
        logging.info(f" REFERENCES FOUND: {len(LoR)}")

        if not LoR:
            logging.info(" No Reference Manuscripts found — UCS may be too strict.")
        else:
            logging.info("\n FIRST FIVE REFERENCES:")
            for ref in LoR[:5]:
                logging.info(
                    f" - [{ref['source']}] {ref['title']} ({ref.get('year', 'N/A')}) → {ref['url']}"
                )

    except Exception as e:
        logging.error("\n[STEP 12 ERROR]")
        logging.error("  Prior-art search failed:")
        logging.error(f"    {str(e)}")
        logging.error("    (Pipeline continues — UCS or APIs may be malformed or unavailable)")
        import traceback

        logging.error(traceback.format_exc())
        final_query, LoR = None, []

    return NAAOutputs(ss=ss, ssr=ssr, ss_synopsis=synopsis, ucs=ucs, lor=LoR)
