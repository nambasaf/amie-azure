import httpx
import urllib.parse
import time
import logging
import asyncio
from typing import List
from math import ceil

EMAIL = "nambasaf@oregonstate.edu"
MAX_PER_PAGE = 200
MAX_RETRIES = 5
TIMEOUT = 20

# Semantic Scholar rate limiting (1 request per second)
_semantic_scholar_last_request = 0.0
_semantic_scholar_lock = None


def _get_semantic_scholar_lock():
    """Initialize lock lazily (needs event loop)"""
    global _semantic_scholar_lock
    if _semantic_scholar_lock is None:
        _semantic_scholar_lock = asyncio.Lock()
    return _semantic_scholar_lock


def reconstruct_abstract(inv_index):
    if not inv_index:
        return ""
    words = sorted(
        [(pos, word) for word, positions in inv_index.items() for pos in positions]
    )
    return " ".join(w for _, w in words)


async def fetch_page(client, url):
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = 2**attempt
                logging.warning(f"OpenAlex 429: Retry {attempt} in {wait}s")
                await asyncio.sleep(wait)
            else:
                logging.warning(f"OpenAlex Error {resp.status_code}: {resp.text}")
                return None
        except httpx.RequestError as e:
            logging.warning(f"OpenAlex Request Error: {e}")
            if attempt == MAX_RETRIES - 1:
                return None
            await asyncio.sleep(2**attempt)
    return None


def sanitize_for_openalex(query: str) -> str:
    """
    Sanitizes a UCS query for OpenAlex compatibility.

    Removes:
    - Proximity operators (NEAR, NEAR/n)
    - Parentheses
    - Quotation marks
    - Boolean operators (AND/OR) -> replaced with spaces

    Preserves key terms as whitespace-separated keywords.
    """
    import re

    # Remove proximity operators (NEAR, NEAR/5, etc.)
    sanitized = re.sub(r"\s+NEAR(?:/\d+)?\s+", " ", query, flags=re.IGNORECASE)

    # Remove parentheses
    sanitized = sanitized.replace("(", "").replace(")", "")

    # Remove quotation marks
    sanitized = sanitized.replace('"', "")

    # Replace AND/OR with spaces
    sanitized = re.sub(r"\s+AND\s+", " ", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+OR\s+", " ", sanitized, flags=re.IGNORECASE)

    # Collapse multiple spaces
    sanitized = re.sub(r"\s+", " ", sanitized).strip()

    # OpenAlex search param max length is 400 characters
    if len(sanitized) > 400:
        sanitized = (
            sanitized[:400].rsplit(" ", 1)[0]
            if " " in sanitized[:400]
            else sanitized[:400]
        )
    return sanitized


OPENALEX_SEARCH_MAX_LEN = 400


async def search_openalex(query: str, limit: int = 50):
    """
    Async search for OpenAlex with sanitization fallback.

    Strategy:
    1. Try original query first
    2. If query fails (500 error or parser failure), sanitize and retry once
    3. If sanitized query fails, return empty list
    """
    # OpenAlex search param max 400 chars
    search_query = (
        query[:OPENALEX_SEARCH_MAX_LEN]
        if len(query) > OPENALEX_SEARCH_MAX_LEN
        else query
    )
    encoded = urllib.parse.quote_plus(search_query)
    base = (
        f"https://api.openalex.org/works"
        f"?search={encoded}"
        f"&select=id,doi,display_name,publication_year,abstract_inverted_index"
        f"&per-page={MAX_PER_PAGE}"
        f"&mailto={EMAIL}"
    )

    results = []
    page = 1

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Try first page with original query
        logging.info(f"OpenAlex Request URL: {base}&page={page}")
        data = await fetch_page(client, f"{base}&page={page}")

        # Check for query incompatibility (500 error or None response or EMPTY results)
        # We treat count=0 as a potential syntax/specificity issue causing "no match"
        is_empty = False
        if data and "meta" in data and data["meta"].get("count", 0) == 0:
            is_empty = True
            logging.warning(
                f"OpenAlex query returned 0 results. Triggering sanitization fallback..."
            )

        if data is None or is_empty:
            if data is None:
                logging.warning(
                    f"OpenAlex query failed (network/server error), attempting sanitization..."
                )

            # Sanitize and retry; cap at 400 chars for OpenAlex
            sanitized_query = sanitize_for_openalex(query)
            if len(sanitized_query) > OPENALEX_SEARCH_MAX_LEN:
                sanitized_query = (
                    sanitized_query[:OPENALEX_SEARCH_MAX_LEN].rsplit(" ", 1)[0]
                    if " " in sanitized_query[:OPENALEX_SEARCH_MAX_LEN]
                    else sanitized_query[:OPENALEX_SEARCH_MAX_LEN]
                )
            logging.info(f"Sanitized query: {sanitized_query[:100]}...")

            encoded_sanitized = urllib.parse.quote_plus(sanitized_query)
            base = (
                f"https://api.openalex.org/works"
                f"?search={encoded_sanitized}"
                f"&select=id,doi,display_name,publication_year,abstract_inverted_index"
                f"&per-page={MAX_PER_PAGE}"
                f"&mailto={EMAIL}"
            )

            logging.info(f"OpenAlex Request URL (Sanitized): {base}&page={page}")
            data = await fetch_page(client, f"{base}&page={page}")

            if data is None:
                logging.error(
                    "OpenAlex sanitized query also failed. Skipping OpenAlex."
                )
                return []
            if data and "meta" in data and data["meta"].get("count", 0) == 0:
                logging.warning("OpenAlex sanitized query returned 0 results.")
                return []

        # Process results
        while len(results) < limit and data:
            items = data.get("results", [])
            if not items:
                break

            for w in items:
                abs_text = reconstruct_abstract(w.get("abstract_inverted_index"))
                results.append(
                    {
                        "id": w["id"],
                        "doi": w.get("doi"),
                        "title": w.get("display_name"),
                        "year": w.get("publication_year"),
                        "abstract": abs_text[:500],
                        "url": w["id"],
                        "source": "OpenAlex",
                    }
                )
                if len(results) >= limit:
                    break

            meta = data.get("meta", {})
            count = meta.get("count", 0)
            if page >= ceil(count / MAX_PER_PAGE):
                break
            page += 1

            data = await fetch_page(client, f"{base}&page={page}")

    return results


# ============================================================================
# PATENTSVIEW SEARCH ENGINE
# ============================================================================


def sanitize_for_patentsview(query: str) -> List[str]:
    """
    Sanitizes UCS for PatentsView and returns keyword tokens.

    Strategy:
    1. Remove proximity operators, parentheses, quotes, boolean operators
    2. Split into individual keyword tokens
    3. Limit to 8-12 most relevant terms to avoid query explosion

    Returns: List of keyword strings (not a dict, not a long string)
    """
    import re

    # Remove proximity operators
    sanitized = re.sub(r"\s+NEAR(?:/\d+)?\s+", " ", query, flags=re.IGNORECASE)

    # Remove parentheses and quotes
    sanitized = sanitized.replace("(", "").replace(")", "").replace('"', "")

    # Replace AND/OR with spaces
    sanitized = re.sub(r"\s+AND\s+", " ", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+OR\s+", " ", sanitized, flags=re.IGNORECASE)

    # Split into tokens
    tokens = sanitized.split()

    # Remove duplicates while preserving order; keep tokens of length >= 2 (e.g. "AI")
    seen = set()
    unique_tokens = []
    for token in tokens:
        token_lower = token.lower()
        if token_lower not in seen and len(token) >= 2:
            seen.add(token_lower)
            unique_tokens.append(token)

    # Limit to 8-12 terms
    limited_tokens = unique_tokens[:12]

    return limited_tokens


async def fetch_patents_with_retry(client, url, payload, headers, max_retries=5):
    """
    Fetch patents with exponential backoff retry logic.
    PatentsView accepts GET with q, f, o as query params (same as POST body).
    """
    import json as _json

    q_enc = urllib.parse.quote(_json.dumps(payload["q"]))
    f_enc = urllib.parse.quote(_json.dumps(payload["f"]))
    o_enc = urllib.parse.quote(_json.dumps(payload["o"]))
    get_url = f"{url}?q={q_enc}&f={f_enc}&o={o_enc}"
    for attempt in range(max_retries):
        try:
            resp = await client.get(get_url, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = 2**attempt
                logging.warning(f"PatentsView 429: Retry {attempt} in {wait}s")
                await asyncio.sleep(wait)
            elif resp.status_code == 403:
                logging.error(
                    "PatentsView 403: Invalid or missing API key. Set PATENTS_VIEW_KEY."
                )
                return None
            else:
                body = resp.text[:400] if resp.text else ""
                logging.warning(
                    f"PatentsView HTTP {resp.status_code}: {body}"
                )
                return None
        except httpx.RequestError as e:
            logging.warning(f"PatentsView Request Error: {e}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(2**attempt)
    return None


async def search_patentsview(query: str, limit: int = 50):
    """
    Async search for PatentsView with keyword tokenization and retry logic.

    Strategy:
    1. Sanitize UCS to extract keyword tokens (8-12 terms)
    2. Search title + abstract ONLY (claims are secondary, per MVP constraint)
    3. If results < target, add claims search (similar to UCS ablation)
    4. Retry with exponential backoff on failures
    5. Preserve inventor metadata for downstream citation
    """
    import os

    api_key = os.getenv("PATENTS_VIEW_KEY")
    if not api_key:
        logging.warning(
            "PATENTS_VIEW_KEY not set — PatentsView requires an API key. "
            "Get one at https://patentsview-support.atlassian.net/servicedesk/customer/portal/1/group/1/create/18"
        )
        return []

    # Sanitize query to get keyword tokens
    keyword_tokens = sanitize_for_patentsview(query)
    # PatentsView _text_any expects a string; fallback to first 80 chars of sanitized query if no tokens
    if keyword_tokens:
        keyword_text = " ".join(keyword_tokens[:10])
        logging.info(
            f"PatentsView search with {len(keyword_tokens)} keywords: {keyword_tokens[:5]}..."
        )
    else:
        import re as _re
        raw = _re.sub(r"\s+NEAR(?:/\d+)?\s+", " ", query, flags=_re.IGNORECASE)
        raw = raw.replace("(", "").replace(")", "").replace('"', "")
        raw = _re.sub(r"\s+AND\s+", " ", raw, flags=_re.IGNORECASE)
        raw = _re.sub(r"\s+OR\s+", " ", raw, flags=_re.IGNORECASE)
        raw = _re.sub(r"\s+", " ", raw).strip()[:80]
        if not raw or len(raw) < 3:
            logging.warning("No usable keywords from UCS for PatentsView")
            return []
        keyword_text = raw
        logging.info(f"PatentsView fallback query (no tokens): {keyword_text[:60]}...")

    # PatentsView API endpoint (see https://search.patentsview.org/docs) — response uses patent_id
    url = "https://search.patentsview.org/api/v1/patent/"

    # Build query payload - title + abstract only (claims are on a different endpoint)
    payload = {
        "q": {
            "_or": [
                {"_text_any": {"patent_title": keyword_text}},
                {"_text_any": {"patent_abstract": keyword_text}},
            ]
        },
        "f": [
            "patent_id",
            "patent_title",
            "patent_date",
            "patent_abstract",
            "inventors.inventor_name_first",
            "inventors.inventor_name_last",
        ],
        "o": {"size": min(limit, 100)},
    }

    results = []

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            headers = {"X-Api-Key": api_key}

            # Try primary query (title + abstract)
            data = await fetch_patents_with_retry(client, url, payload, headers)

            if data is None:
                logging.error("PatentsView primary query failed after retries")
                return []

            patents = data.get("patents", [])
            logging.info(
                f"PatentsView response: {len(patents)} patents (total_hits may differ)"
            )
            if data.get("error"):
                logging.warning(f"PatentsView API error flag: {data.get('error')}")

            # Process results (API returns patent_id per Endpoint Dictionary)
            for p in patents:
                patent_num = p.get("patent_id") or p.get("patent_number")
                if not patent_num:
                    continue
                title = p.get("patent_title", "Untitled Patent")
                abstract = p.get("patent_abstract", "")
                date = p.get("patent_date", "")

                # Extract year from date (format: YYYY-MM-DD)
                year = int(date.split("-")[0]) if date else None

                # Collect inventor names (nested list from API; field names vary by API version)
                inventors_list = p.get("inventors", [])
                inventors = []
                for inv in inventors_list if isinstance(inventors_list, list) else []:
                    first = (
                        inv.get("inventor_name_first")
                        or inv.get("inventor_first_name")
                        or ""
                    ).strip()
                    last = (
                        inv.get("inventor_name_last")
                        or inv.get("inventor_last_name")
                        or ""
                    ).strip()
                    if first or last:
                        inventors.append(f"{last}, {first[0]}." if first else last)

                # Build Google Patents URL
                google_url = f"https://patents.google.com/patent/US{patent_num}"

                # Build result with metadata
                results.append(
                    {
                        "id": patent_num,
                        "title": title,
                        "year": year,
                        "abstract": abstract[:500],
                        "url": google_url,
                        "source": "PatentsView",
                        "metadata": {
                            "inventors": inventors,
                            "patent_date": date,
                            "patent_number": patent_num,
                        },
                    }
                )

                if len(results) >= limit:
                    break

            # Log first 5 for manual verification (MVP requirement)
            if results:
                logging.info("\n===== FIRST FIVE PATENT REFERENCES =====")
                for i, ref in enumerate(results[:5], 1):
                    logging.info(f"{i}. {ref['title']} -> {ref['url']}")
                logging.info("=" * 40)

    except Exception as e:
        logging.error(f"PatentsView search failed: {e}")
        return []

    return results


# ============================================================================
# SEMANTIC SCHOLAR SEARCH ENGINE
# ============================================================================


def sanitize_for_semantic_scholar(query: str) -> str:
    """
    Sanitizes a UCS query for Semantic Scholar compatibility.

    Removes:
    - Proximity operators (NEAR, NEAR/n)
    - Parentheses
    - Quotation marks
    - Boolean operators (AND/OR) -> replaced with spaces

    Preserves key terms as whitespace-separated keywords.
    """
    import re

    # Remove proximity operators (NEAR, NEAR/5, etc.)
    sanitized = re.sub(r"\s+NEAR(?:/\d+)?\s+", " ", query, flags=re.IGNORECASE)

    # Remove parentheses
    sanitized = sanitized.replace("(", "").replace(")", "")

    # Remove quotation marks
    sanitized = sanitized.replace('"', "")

    # Replace AND/OR with spaces
    sanitized = re.sub(r"\s+AND\s+", " ", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+OR\s+", " ", sanitized, flags=re.IGNORECASE)

    # Collapse multiple spaces
    sanitized = re.sub(r"\s+", " ", sanitized).strip()

    return sanitized


async def fetch_semantic_scholar_page(client, url, headers):
    """
    Fetch Semantic Scholar page with exponential backoff retry logic.
    Enforces 1 request per second rate limit.
    """
    global _semantic_scholar_last_request

    # Rate limiting: ensure at least 1 second between requests
    lock = _get_semantic_scholar_lock()
    async with lock:
        current_time = asyncio.get_event_loop().time()
        time_since_last = current_time - _semantic_scholar_last_request
        if time_since_last < 1.0:
            wait_time = 1.0 - time_since_last
            logging.debug(f"Semantic Scholar rate limit: waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)
        _semantic_scholar_last_request = asyncio.get_event_loop().time()

    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url, headers=headers)

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                # If we hit 429, wait longer (rate limit exceeded)
                wait = max(2**attempt, 2.0)  # At least 2 seconds
                logging.warning(
                    f"Semantic Scholar 429: Rate limit exceeded. Waiting {wait}s"
                )
                await asyncio.sleep(wait)
                # Update last request time after waiting
                lock = _get_semantic_scholar_lock()
                async with lock:
                    _semantic_scholar_last_request = asyncio.get_event_loop().time()
            elif resp.status_code == 401:
                logging.error("Semantic Scholar 401: Invalid API key")
                return None
            else:
                logging.warning(
                    f"Semantic Scholar Error {resp.status_code}: {resp.text[:200]}"
                )
                return None

        except httpx.RequestError as e:
            logging.warning(f"Semantic Scholar Request Error: {e}")
            if attempt == MAX_RETRIES - 1:
                return None
            await asyncio.sleep(2**attempt)

    return None


async def search_semantic_scholar(query: str, limit: int = 50):
    """
    Async search for Semantic Scholar with sanitization fallback.

    Strategy:
    1. Try original query first
    2. If query fails (500 error or empty results), sanitize and retry once
    3. If sanitized query fails, return empty list
    """
    import os

    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    # API key is optional; without it rate limits are stricter but search still works
    headers = {"x-api-key": api_key} if api_key else {}

    # Encode original query
    encoded = urllib.parse.quote_plus(query)
    base_url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={encoded}"
        f"&limit={min(limit, 100)}"  # Semantic Scholar max is 100 per request
        f"&fields=title,abstract,year,publicationDate,paperId,doi"
    )

    results = []

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Try first with original query
        logging.info(f"Semantic Scholar Request URL: {base_url[:100]}...")
        data = await fetch_semantic_scholar_page(client, base_url, headers)

        # Check for query incompatibility or empty results
        is_empty = False
        if data and "data" in data and len(data.get("data", [])) == 0:
            is_empty = True
            logging.warning(
                "Semantic Scholar query returned 0 results. Triggering sanitization fallback..."
            )

        if data is None or is_empty:
            if data is None:
                logging.warning(
                    "Semantic Scholar query failed (network/server error), attempting sanitization..."
                )

            # Sanitize and retry
            sanitized_query = sanitize_for_semantic_scholar(query)
            logging.info(f"Sanitized query: {sanitized_query[:100]}...")

            encoded_sanitized = urllib.parse.quote_plus(sanitized_query)
            base_url = (
                f"https://api.semanticscholar.org/graph/v1/paper/search"
                f"?query={encoded_sanitized}"
                f"&limit={min(limit, 100)}"
                f"&fields=title,abstract,year,publicationDate,paperId,doi"
            )

            logging.info(
                f"Semantic Scholar Request URL (Sanitized): {base_url[:100]}..."
            )
            data = await fetch_semantic_scholar_page(client, base_url, headers)

            if data is None:
                logging.error(
                    "Semantic Scholar sanitized query also failed. Skipping Semantic Scholar."
                )
                return []
            if data and "data" in data and len(data.get("data", [])) == 0:
                logging.warning("Semantic Scholar sanitized query returned 0 results.")
                return []

        # Process results
        papers = data.get("data", [])
        for paper in papers[:limit]:
            paper_id = paper.get("paperId", "")
            title = paper.get("title", "Untitled")
            abstract = paper.get("abstract", "")
            year = paper.get("year")
            publication_date = paper.get("publicationDate")
            doi = paper.get("doi")

            # Build URL (Semantic Scholar paper page)
            url = (
                f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else ""
            )

            # Format publication date
            if publication_date:
                pub_date = publication_date
            elif year:
                pub_date = f"{year}-01-01"
            else:
                pub_date = "1900-01-01"

            results.append(
                {
                    "id": paper_id,
                    "doi": doi,
                    "title": title,
                    "year": year,
                    "abstract": abstract[:500] if abstract else "",
                    "url": url,
                    "source": "SemanticScholar",
                }
            )

            if len(results) >= limit:
                break

    return results
