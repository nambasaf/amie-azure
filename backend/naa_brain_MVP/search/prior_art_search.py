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

def reconstruct_abstract(inv_index):
    if not inv_index:
        return ""
    words = sorted([(pos, word) for word, positions in inv_index.items()
                    for pos in positions])
    return " ".join(w for _, w in words)

async def fetch_page(client, url):
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = 2 ** attempt
                logging.warning(f"OpenAlex 429: Retry {attempt} in {wait}s")
                await asyncio.sleep(wait)
            else:
                logging.warning(f"OpenAlex Error {resp.status_code}: {resp.text}")
                return None
        except httpx.RequestError as e:
            logging.warning(f"OpenAlex Request Error: {e}")
            if attempt == MAX_RETRIES - 1:
                return None
            await asyncio.sleep(2 ** attempt)
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
    sanitized = re.sub(r'\s+NEAR(?:/\d+)?\s+', ' ', query, flags=re.IGNORECASE)
    
    # Remove parentheses
    sanitized = sanitized.replace('(', '').replace(')', '')
    
    # Remove quotation marks
    sanitized = sanitized.replace('"', '')
    
    # Replace AND/OR with spaces
    sanitized = re.sub(r'\s+AND\s+', ' ', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'\s+OR\s+', ' ', sanitized, flags=re.IGNORECASE)
    
    # Collapse multiple spaces
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    
    return sanitized

async def search_openalex(query: str, limit: int = 50):
    """
    Async search for OpenAlex with sanitization fallback.
    
    Strategy:
    1. Try original query first
    2. If query fails (500 error or parser failure), sanitize and retry once
    3. If sanitized query fails, return empty list
    """
    encoded = urllib.parse.quote_plus(query)
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
        data = await fetch_page(client, f"{base}&page={page}")
        
        # Check for query incompatibility (500 error or None response)
        if data is None:
            logging.warning(f"OpenAlex query failed, attempting sanitization...")
            
            # Sanitize and retry
            sanitized_query = sanitize_for_openalex(query)
            logging.info(f"Sanitized query: {sanitized_query[:100]}...")
            
            encoded_sanitized = urllib.parse.quote_plus(sanitized_query)
            base = (
                f"https://api.openalex.org/works"
                f"?search={encoded_sanitized}"
                f"&select=id,doi,display_name,publication_year,abstract_inverted_index"
                f"&per-page={MAX_PER_PAGE}"
                f"&mailto={EMAIL}"
            )
            
            data = await fetch_page(client, f"{base}&page={page}")
            
            if data is None:
                logging.error("OpenAlex sanitized query also failed. Skipping OpenAlex.")
                return []
        
        # Process results
        while len(results) < limit and data:
            items = data.get("results", [])
            if not items:
                break
                
            for w in items:
                abs_text = reconstruct_abstract(w.get("abstract_inverted_index"))
                results.append({
                    "id": w["id"],
                    "doi": w.get("doi"),
                    "title": w.get("display_name"),
                    "year": w.get("publication_year"),
                    "abstract": abs_text[:500],
                    "url": w["id"],
                    "source": "OpenAlex"
                })
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
    sanitized = re.sub(r'\s+NEAR(?:/\d+)?\s+', ' ', query, flags=re.IGNORECASE)
    
    # Remove parentheses and quotes
    sanitized = sanitized.replace('(', '').replace(')', '').replace('"', '')
    
    # Replace AND/OR with spaces
    sanitized = re.sub(r'\s+AND\s+', ' ', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'\s+OR\s+', ' ', sanitized, flags=re.IGNORECASE)
    
    # Split into tokens
    tokens = sanitized.split()
    
    # Remove duplicates while preserving order
    seen = set()
    unique_tokens = []
    for token in tokens:
        token_lower = token.lower()
        if token_lower not in seen and len(token) > 2:  # Skip very short tokens
            seen.add(token_lower)
            unique_tokens.append(token)
    
    # Limit to 8-12 terms
    limited_tokens = unique_tokens[:12]
    
    return limited_tokens

async def fetch_patents_with_retry(client, url, payload, headers, max_retries=5):
    """
    Fetch patents with exponential backoff retry logic.
    Mirrors OpenAlex retry semantics.
    """
    for attempt in range(max_retries):
        try:
            resp = await client.post(url, json=payload, headers=headers)
            
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = 2 ** attempt
                logging.warning(f"PatentsView 429: Retry {attempt} in {wait}s")
                await asyncio.sleep(wait)
            else:
                logging.warning(f"PatentsView Error {resp.status_code}: {resp.text[:200]}")
                return None
                
        except httpx.RequestError as e:
            logging.warning(f"PatentsView Request Error: {e}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(2 ** attempt)
    
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
        logging.error("PATENTS_VIEW_KEY not found in environment")
        return []
    
    # Sanitize query to get keyword tokens
    keyword_tokens = sanitize_for_patentsview(query)
    keyword_text = " ".join(keyword_tokens)

    
    if not keyword_tokens:
        logging.warning("No keywords extracted from UCS for PatentsView")
        return []

    logging.info(
        f"PatentsView search with {len(keyword_tokens)} keywords: {keyword_tokens[:5]}..."
    )

    
    # PatentsView API endpoint
    url = "https://search.patentsview.org/api/v1/patent/"
    
    # Build query payload - PRIMARY: title + abstract only
    payload = {
    "q": {
        "_or": [
            {"_text_any": {"patent_title": keyword_text}},
            {"_text_any": {"patent_abstract": keyword_text}}
        ]
    },
        "f": [
            "patent_number",
            "patent_title", 
            "patent_date",
            "patent_abstract",
            "inventor_first_name",
            "inventor_last_name"
        ],
        "o": {
            "per_page": min(limit, 100)
        }
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
            
            # If insufficient results, try adding claims (secondary search)
            if len(patents) < limit:
                logging.info(f"PatentsView primary search returned {len(patents)} results. Adding claims search...")
                
                payload_with_claims = {
                    "q": {
                        "_or": [
                            {"_text_any": {"patent_title": keyword_text}},
                            {"_text_any": {"patent_abstract": keyword_text}},
                            {"_text_any": {"claims": keyword_text}}
                        ]
                    },
                    "f": payload["f"],
                    "o": payload["o"]
                }
                
                data = await fetch_patents_with_retry(client, url, payload_with_claims, headers)
                
                if data:
                    patents = data.get("patents", [])
                    logging.info(f"PatentsView with claims: {len(patents)} results")

            
            # Process results
            for p in patents:
                patent_num = p.get("patent_number")
                title = p.get("patent_title", "Untitled Patent")
                abstract = p.get("patent_abstract", "")
                date = p.get("patent_date", "")
                
                # Extract year from date (format: YYYY-MM-DD)
                year = int(date.split("-")[0]) if date else None
                
                # Collect inventor names
                first_names = p.get("inventor_first_name", [])
                last_names = p.get("inventor_last_name", [])
                
                inventors = []
                for i in range(max(len(first_names), len(last_names))):
                    first = first_names[i] if i < len(first_names) else ""
                    last = last_names[i] if i < len(last_names) else ""
                    if first or last:
                        inventors.append(f"{last}, {first[0]}." if first else last)
                
                # Build Google Patents URL
                google_url = f"https://patents.google.com/patent/US{patent_num}"
                
                # Build result with metadata
                results.append({
                    "id": patent_num,
                    "title": title,
                    "year": year,
                    "abstract": abstract[:500],
                    "url": google_url,
                    "source": "PatentsView",
                    "metadata": {
                        "inventors": inventors,
                        "patent_date": date,
                        "patent_number": patent_num
                    }
                })
                
                if len(results) >= limit:
                    break
            
            # Log first 5 for manual verification (MVP requirement)
            if results:
                logging.info("\n===== FIRST FIVE PATENT REFERENCES =====")
                for i, ref in enumerate(results[:5], 1):
                    logging.info(f"{i}. {ref['title']} → {ref['url']}")
                logging.info("=" * 40)
            
    except Exception as e:
        logging.error(f"PatentsView search failed: {e}")
        return []
    
    return results

