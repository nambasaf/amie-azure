import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "incomplete", "expired"}
EXPERT_ROLE_PROMPT = (
    "Act as a senior patent analyst with specific expertise across all of the "
    "science and engineering fields listed in the Fields Map."
)


def _build_client() -> OpenAI:
    base_url = os.getenv("DEEP_RESEARCH_BASE_URL") or os.getenv("PROJECT_ENDPOINT")
    if not base_url:
        raise ValueError("Missing PROJECT_ENDPOINT or DEEP_RESEARCH_BASE_URL for Deep Research")

    base_url = base_url.rstrip("/")
    if not base_url.endswith("/openai/v1"):
        base_url = f"{base_url}/openai/v1"
    if ".openai.azure.com" not in base_url:
        logging.warning(
            "[DEEP RESEARCH] Base URL does not look like the Azure OpenAI endpoint "
            f"recommended by Microsoft docs: {base_url}"
        )

    api_key = os.getenv("DEEP_RESEARCH_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
    if api_key:
        logging.info("[DEEP RESEARCH] Auth mode: API key")
        return OpenAI(base_url=f"{base_url}/", api_key=api_key)

    logging.warning("[DEEP RESEARCH] Auth mode: DefaultAzureCredential fallback")
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://ai.azure.com/.default"
    )
    return OpenAI(base_url=f"{base_url}/", api_key=token_provider)


def _extract_json_object(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("Deep Research returned empty output")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("Deep Research output did not contain parseable JSON")
    return json.loads(match.group(0))


def _detect_patent_id(reference: Dict[str, Any]) -> str | None:
    for key in ("patent_id", "id", "url", "title"):
        value = reference.get(key)
        if not value:
            continue
        text = str(value)
        patterns = [
            r"\bUS\d+[A-Z0-9]*\b",
            r"\bWO\d{4}\d+[A-Z0-9]*\b",
            r"\bEP\d+[A-Z0-9]*\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).upper()
    return None


def _infer_source(reference: Dict[str, Any]) -> str:
    patent_id = _detect_patent_id(reference)
    if patent_id:
        return "PatentsView"

    url = (reference.get("url") or "").lower()
    if "openalex.org" in url:
        return "OpenAlex"
    if "semanticscholar.org" in url:
        return "Semantic Scholar"

    source = (reference.get("source") or "").strip()
    return source or "Deep Research"


def _normalize_reference(reference: Dict[str, Any]) -> Dict[str, Any]:
    patent_id = _detect_patent_id(reference)
    source = _infer_source(reference)
    title = (reference.get("title") or reference.get("citation") or "Untitled").strip()
    url = (reference.get("url") or "").strip()

    return {
        "id": patent_id or reference.get("id") or reference.get("doi") or url or title,
        "patent_id": patent_id,
        "doi": reference.get("doi"),
        "title": title,
        "year": reference.get("year"),
        "abstract": reference.get("why_relevant")
        or reference.get("summary")
        or reference.get("abstract")
        or "",
        "url": url,
        "source": source,
        "retrieved_by": ["deep_research"],
    }


def _coerce_reference_list(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("references", "results", "sources", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            normalized = []
            for item in value:
                if isinstance(item, dict) and item.get("url"):
                    normalized.append(_normalize_reference(item))
            return normalized
    return []


def _build_prompt(
    ucs: str,
    synopsis: str,
    source_structure: List[Any],
    reference_limit: int = 50,
) -> str:
    ss_json = json.dumps(source_structure, default=str, indent=2)
    return f"""
{EXPERT_ROLE_PROMPT}

You are supporting a novelty-assessment pipeline for technical manuscripts.

Find prior-art references for the manuscript concept below. Use web search and multi-step reasoning.
Prioritize references that are likely retrievable downstream:
- patents: prefer Google Patents or other patent pages with a clear patent number
- papers: prefer OpenAlex work URLs, direct PDF URLs, arXiv PDF URLs, or stable scholarly pages

Return ONLY valid JSON with this schema:
{{
  "references": [
    {{
      "title": "string",
      "url": "https://...",
      "source": "OpenAlex | Semantic Scholar | PatentsView | Google Patents | arXiv | Journal | Other",
      "year": 2024,
      "doi": "string or null",
      "id": "optional patent number or work identifier",
      "why_relevant": "1-2 sentence explanation"
    }}
  ]
}}

Rules:
- Return at most {reference_limit} references.
- Prefer the most relevant and technically similar references.
- Include patents when appropriate.
- Do not include any prose before or after the JSON.

Unified Composite Search String:
{ucs}

Source Structure Synopsis:
{synopsis}

Source Structure Blocks:
{ss_json}
""".strip()


def _create_response(
    client: OpenAI,
    model: str,
    tool_type: str,
    prompt: str,
    *,
    max_output_tokens: int | None = None,
    max_tool_calls: int | None = None,
):
    request_kwargs: Dict[str, Any] = {
        "model": model,
        "background": True,
        "tools": [{"type": tool_type}],
        "input": prompt,
    }
    if max_output_tokens is not None:
        request_kwargs["max_output_tokens"] = max_output_tokens
    if max_tool_calls is not None:
        request_kwargs["max_tool_calls"] = max_tool_calls
    return client.responses.create(
        **request_kwargs,
    )


def _response_output_text(response: Any) -> str:
    return getattr(response, "output_text", "") or ""


def _response_incomplete_reason(response: Any) -> str | None:
    details = getattr(response, "incomplete_details", None)
    if not details:
        return None
    if isinstance(details, dict):
        return details.get("reason")
    return getattr(details, "reason", None)


def _poll_until_terminal(client: OpenAI, response: Any) -> Any:
    response_id = response.id
    status = getattr(response, "status", None)
    while status not in TERMINAL_STATUSES:
        logging.info(f"[DEEP RESEARCH] Polling response {response_id} (status={status})")
        import time

        time.sleep(10)
        response = client.responses.retrieve(response_id)
        status = getattr(response, "status", None)
    return response


def _start_response_with_tool_fallback(
    client: OpenAI,
    model: str,
    prompt: str,
    tool_attempts: List[str],
    *,
    max_output_tokens: int | None = None,
    max_tool_calls: int | None = None,
):
    response = None
    last_error = None
    for tool_type in tool_attempts:
        try:
            logging.info(f"[DEEP RESEARCH] Starting background run with tool '{tool_type}'")
            response = _create_response(
                client,
                model,
                tool_type,
                prompt,
                max_output_tokens=max_output_tokens,
                max_tool_calls=max_tool_calls,
            )
            logging.info(
                f"[DEEP RESEARCH] Request accepted by model "
                f"(response_id={response.id}, initial_status={getattr(response, 'status', None)})"
            )
            return response, tool_type
        except Exception as exc:
            last_error = exc
            logging.warning(f"[DEEP RESEARCH] Failed to start with tool '{tool_type}': {exc}")

    raise last_error or RuntimeError("Deep Research request could not be created")


def _parse_references_from_response(response: Any) -> List[Dict[str, Any]]:
    output_text = _response_output_text(response)
    payload = _extract_json_object(output_text)
    references = _coerce_reference_list(payload)
    logging.info(f"[DEEP RESEARCH] Retrieved {len(references)} normalized references")
    return references


def _run_deep_research_sync(ucs: str, synopsis: str, source_structure: List[Any]) -> List[Dict[str, Any]]:
    client = _build_client()
    model = os.getenv("DEEP_RESEARCH_DEPLOYMENT", "o3-deep-research")
    base_url = os.getenv("DEEP_RESEARCH_BASE_URL") or os.getenv("PROJECT_ENDPOINT")
    reference_limit = int(os.getenv("DEEP_RESEARCH_REFERENCE_LIMIT", 50))
    retry_reference_limit = int(os.getenv("DEEP_RESEARCH_RETRY_REFERENCE_LIMIT", 20))
    max_output_tokens = int(os.getenv("DEEP_RESEARCH_MAX_OUTPUT_TOKENS", 25000))
    max_tool_calls_env = os.getenv("DEEP_RESEARCH_MAX_TOOL_CALLS", "").strip()
    max_tool_calls = int(max_tool_calls_env) if max_tool_calls_env else None
    prompt = _build_prompt(ucs, synopsis, source_structure, reference_limit=reference_limit)
    logging.info(f"[DEEP RESEARCH] Base URL: {base_url}")
    logging.info(f"[DEEP RESEARCH] Deployment: {model}")
    logging.info(f"[DEEP RESEARCH] Reference limit: {reference_limit}")
    logging.info(f"[DEEP RESEARCH] Max output tokens: {max_output_tokens}")
    configured_tool = os.getenv("DEEP_RESEARCH_TOOL_TYPE", "web_search_preview")
    tool_attempts = [configured_tool]
    alternate_tool = "web_search_preview" if configured_tool == "web_search" else "web_search"
    if alternate_tool not in tool_attempts:
        tool_attempts.append(alternate_tool)

    response, tool_used = _start_response_with_tool_fallback(
        client,
        model,
        prompt,
        tool_attempts,
        max_output_tokens=max_output_tokens,
        max_tool_calls=max_tool_calls,
    )
    response = _poll_until_terminal(client, response)
    status = getattr(response, "status", None)

    if status == "completed":
        return _parse_references_from_response(response)

    incomplete_reason = _response_incomplete_reason(response)
    partial_output = _response_output_text(response)
    if status == "incomplete":
        logging.error(
            "[DEEP RESEARCH] Response ended incomplete"
            f" (reason={incomplete_reason or 'unknown'}, tool={tool_used})"
        )
        if partial_output:
            try:
                references = _parse_references_from_response(response)
                if references:
                    logging.warning(
                        f"[DEEP RESEARCH] Salvaged {len(references)} references from incomplete output"
                    )
                    return references
            except Exception as exc:
                logging.warning(f"[DEEP RESEARCH] Could not salvage incomplete output: {exc}")

        if incomplete_reason == "max_output_tokens" and retry_reference_limit < reference_limit:
            logging.warning(
                "[DEEP RESEARCH] Retrying after max_output_tokens with a smaller reference limit"
            )
            retry_prompt = _build_prompt(
                ucs,
                synopsis,
                source_structure,
                reference_limit=retry_reference_limit,
            )
            retry_response, retry_tool = _start_response_with_tool_fallback(
                client,
                model,
                retry_prompt,
                [tool_used],
                max_output_tokens=max_output_tokens,
                max_tool_calls=max_tool_calls,
            )
            retry_response = _poll_until_terminal(client, retry_response)
            retry_status = getattr(retry_response, "status", None)
            if retry_status == "completed":
                return _parse_references_from_response(retry_response)

            retry_reason = _response_incomplete_reason(retry_response)
            raise RuntimeError(
                "Deep Research retry ended with status "
                f"'{retry_status}' (reason={retry_reason or 'unknown'})"
            )

        raise RuntimeError(
            f"Deep Research ended with status 'incomplete' (reason={incomplete_reason or 'unknown'})"
        )

    raise RuntimeError(f"Deep Research ended with status '{status}'")


async def deep_research_lor(ucs: str, synopsis: str, source_structure: List[Any]) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_run_deep_research_sync, ucs, synopsis, source_structure)
