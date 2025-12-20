import os
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any

from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import MessageRole
from azure.identity import DefaultAzureCredential
# from naa_brain_MVP.search.prior_art_search import progressive_search  <-- Removed

# ---------------------------------------------------------------------
# LOAD ENVIRONMENT
# ---------------------------------------------------------------------
load_dotenv()

PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT")

# Agent IDs for each step (must exist in your project)
SS_AGENT_ID = os.getenv("SS_Agent_ID")
SSR_AGENT_ID = os.getenv("SSR_Agent_ID")
SS_SYNOPSIS_AGENT_ID = os.getenv("SS_Synopsis_Agent_ID")
UCS_BUILDER_AGENT_ID = os.getenv("UCS_Builder_Agent_ID")

if not PROJECT_ENDPOINT:
    raise ValueError("PROJECT_ENDPOINT must be set in .env")

missing_ids = []
if not SS_AGENT_ID:
    missing_ids.append("SS_Agent_ID")
if not SSR_AGENT_ID:
    missing_ids.append("SSR_Agent_ID")
if not SS_SYNOPSIS_AGENT_ID:
    missing_ids.append("SS_Synopsis_Agent_ID")
if not UCS_BUILDER_AGENT_ID:
    missing_ids.append("UCS_Builder_Agent_ID")

if missing_ids:
    raise ValueError(f"Missing agent IDs in .env: {', '.join(missing_ids)}")

# ---------------------------------------------------------------------
# AZURE CLIENT
# ---------------------------------------------------------------------
agents_client = AgentsClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(
        exclude_environment_credential=True,
        exclude_managed_identity_credential=True,
    ),
)

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
    # 1. Create thread
    thread = agents_client.threads.create()

    # 2. Send user message
    agents_client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,   # only user/assistant are allowed
        content=prompt,
    )

    # 3. Run agent
    _ = agents_client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent_id,
    )

    # 4. Collect assistant response
    msgs = list(agents_client.messages.list(thread_id=thread.id))
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
                        text = text[len(lang):].strip()

            # Final sanity: ensure clean JSON starts correctly if JSON expected
            text = text.strip()

            return text

    raise RuntimeError(f"No assistant output returned for agent {agent_id}.")

# ---------------------------------------------------------------------
# RETRY WRAPPER
# ---------------------------------------------------------------------
def retry_agent(callable_fn, agent_name: str):
    """
    Retry wrapper for NAA agents (Steps 8-11).
    
    Executes the callable inside a while True loop.
    Catches all exceptions and retries until success.
    Logs each failure and retry attempt.
    
    Args:
        callable_fn: A callable (lambda or function) that executes the agent
        agent_name: Human-readable name for logging (e.g., "SS Agent")
    
    Returns:
        The result of callable_fn on first successful execution
    """
    while True:
        try:
            result = callable_fn()
            return result
        except Exception as e:
            print(f"\n[RETRY] {agent_name} failed:")
            print(f"  {str(e)}")
            print(f"Retrying {agent_name}...\n")
            # Loop continues, callable will be re-executed

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
def build_source_structure(manuscript_text: str, idca_output: str) -> SourceStructure:
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

    raw = _chat(SS_AGENT_ID, prompt)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Step 8 (SS) agent did not return valid JSON. Raw output:\n{raw}"
        ) from e

    if "source_structure" not in data:
        raise RuntimeError(f"JSON from SS agent missing 'source_structure' key. Got:\n{data}")

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
def build_ssr(ss: SourceStructure) -> StructuralScoringRubric:
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

    raw = _chat(SSR_AGENT_ID, prompt)

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
def ss_synopsis(ss: SourceStructure) -> str:
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

    out = _chat(SS_SYNOPSIS_AGENT_ID, prompt)
    return out.strip()

# ---------------------------------------------------------------------
# STEP 11 — UNIFIED COMPOSITE SEARCH STRING (UCS)
# ---------------------------------------------------------------------
def build_ucs(ss: SourceStructure) -> str:
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

    ucs = _chat(UCS_BUILDER_AGENT_ID, prompt)
    # normalize whitespace
    return " ".join(ucs.split())

# ---------------------------------------------------------------------
# PIPELINE ORCHESTRATOR (8–11)
# ---------------------------------------------------------------------
def run_steps_8_to_12(manuscript_text: str, idca_output: str) -> NAAOutputs:
    print("Starting NAA workflow...\n")

    # -------------------- STEP 8 --------------------
    print("\n===== SOURCE STRUCTURE (SS) =====")
    ss = retry_agent(
        lambda: build_source_structure(manuscript_text, idca_output),
        "SS Agent"
    )
    print(" [SS AGENT OUTPUT]")
    for blk in ss.blocks:
        print("  ", blk)
    print("\n")

    # -------------------- STEP 9 --------------------
    print("\n [SSR AGENT] Building Structural Scoring Rubric...")
    ssr = retry_agent(
        lambda: build_ssr(ss),
        "SSR Agent"
    )
    print("[SSR AGENT OUTPUT]")
    for item in ssr.items:
        print("  ", item)
    print("\n")

    print("\n[SSR TABLE]")
    print(render_ssr_table(ssr))
    print("\n")


    # -------------------- STEP 10 --------------------
    print("\n[SS SYNOPSIS AGENT] Creating Source Structure Synopsis...")
    synopsis = retry_agent(
        lambda: ss_synopsis(ss),
        "SS Synopsis Agent"
    )
    print(" [SS SYNOPSIS OUTPUT]")
    print("  ", synopsis)
    print("\n")

    # -------------------- STEP 11 --------------------
    print("\n [UCS AGENT] Generating Unified Composite Search String...")
    ucs = retry_agent(
        lambda: build_ucs(ss),
        "UCS Agent"
    )
    print("[UCS OUTPUT]")
    print("  ", ucs)
    print("\n")

    # -------------------- STEP 12 --------------------
    print("\n [PRIOR ART SEARCH] Executing PARALLEL PROGRESSIVE SEARCH (OpenAlex + Patents + Web)...")
    
    # We need to run the async search from this synchronous function
    import asyncio
    from naa_brain_MVP.search.search_orchestrator import progressive_search as parallel_progressive_search
    
    try:
        # Run async loop
        final_query, LoR = asyncio.run(parallel_progressive_search(ucs, target_total=5))

        print("\n[STEP 12 OUTPUT]")
        print(" PRIOR ART QUERY:", final_query if final_query else "(none)")
        print(" REFERENCES FOUND:", len(LoR))

        if not LoR:
            print(" No Reference Manuscripts found — UCS may be too strict.")
        else:
            print("\n FIRST FIVE REFERENCES:")
            for ref in LoR[:5]:
                print(f" - [{ref['source']}] {ref['title']} ({ref['year']}) → {ref['url']}")

    except Exception as e:
        print("\n[STEP 12 ERROR]")
        print("  Prior-art search failed:")
        print("    ", str(e))
        print("    (Pipeline continues — UCS or APIs may be malformed or unavailable)")
        import traceback
        traceback.print_exc()
        final_query, LoR = None, []

    return NAAOutputs(ss=ss, ssr=ssr, ss_synopsis=synopsis, ucs=ucs, lor=LoR)
