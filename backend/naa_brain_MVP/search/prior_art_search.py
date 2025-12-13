# -------- STUBS RN ------
# the ucs needs to be better refined inorder to have correct RMs retrieved in the prior art search
# parallel search with our other apis 
# combine with the other references 


import requests
import urllib.parse
import time
import logging
from math import ceil
from typing import List


TIMEOUT = 20
EMAIL = "nambasaf@oregonstate.edu"
MAX_PER_PAGE = 200
MAX_RETRIES = 5


def reconstruct_abstract(inv_index):
    if not inv_index:
        return ""
    words = sorted([(pos, word) for word, positions in inv_index.items()
                    for pos in positions])
    return " ".join(w for _, w in words)


def fetch_page(url):
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            wait = 2 ** attempt
            logging.warning(
                f"Retry {attempt} in {wait}s for status={r.status_code}")
            time.sleep(wait)
        except requests.exceptions.Timeout:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("OpenAlex request failed after retries")


def openalex_search(query, limit=50):
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

    while len(results) < limit:
        data = fetch_page(f"{base}&page={page}")
        for w in data.get("results", []):
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

        if page >= ceil(data["meta"]["count"] / MAX_PER_PAGE):
            break
        page += 1

    return results

# STEP 12 — PROGRESSIVE STRUCTURAL SEARCH ENGINE


def query_variants(block: str) -> List[str]:
    words = block.lower().split()
    core = words[0] if words else block.lower()

    return [
        f"\"{block}\"",   # exact phrase
        block,            # original form
        core,             
    ]


def split_ucs(ucs: str) -> List[str]:
    blocks = []
    current = []
    depth = 0
    in_quotes = False

    i = 0
    while i < len(ucs):
        ch = ucs[i]

        # Track quotes
        if ch == '"':
            in_quotes = not in_quotes

        # Track parentheses
        elif ch == '(' and not in_quotes:
            depth += 1
        elif ch == ')' and not in_quotes:
            depth -= 1

        # Detect top-level AND
        if not in_quotes and depth == 0 and ucs[i:i+4].upper() == " AND":
            blocks.append("".join(current).strip())
            current = []
            i += 4
            continue

        current.append(ch)
        i += 1

    if current:
        blocks.append("".join(current).strip())
    return blocks


def progressive_search(ucs: str, target_total=5, batch_limit=50):
    """
    Correct Step 12 implementation:
    1. Test the full UCS.
    2. If too strict (0 results), remove one block at a time.
    3. Accumulate unique RMs until target_total reached.
    """

    print("\n===== UCS-BASED PROGRESSIVE SEARCH ENGINE =====\n")

    blocks = split_ucs(ucs)
    LoR = []
    seen_ids = set()
    final_query = None

    # --------------------------------------------------
    # 1) TEST FULL UCS FIRST
    # --------------------------------------------------
    print("[FULL QUERY TEST]")
    print("  Testing UCS:\n   ", ucs)
    results = openalex_search(ucs, batch_limit)
    print(f"  → {len(results)} result(s)")

    # add unique results
    for r in results:
        if r["id"] not in seen_ids:
            LoR.append(r)
            seen_ids.add(r["id"])

    if 5 <= len(LoR) <= 250:
        print("\n SUCCESS — FULL UCS WAS VALID")
        return ucs, LoR

    if len(LoR) == 0:
        print("\n FULL QUERY TOO STRICT — BEGINNING BLOCK REMOVAL...")
    else:
        print("\n FULL QUERY RETURNED <5 RESULTS — BROADENING SEARCH...")

    # --------------------------------------------------
    # 2) START BLOCK ELIMINATION SEARCH
    # --------------------------------------------------
    for i in range(len(blocks)):
        print("\n-------------------------------------------")
        print(f"[BLOCK ELIMINATION ROUND {i+1}] Removing block:")
        print(f"    {blocks[i]}")

        test_blocks = blocks[:i] + blocks[i+1:]

        # Prevent empty query
        if not test_blocks:
            print("    Skipping — removing this block leaves query empty.")
            continue

        query = " AND ".join(test_blocks)
        final_query = query

        print(f"   Testing Query:\n   {query}")
        results = openalex_search(query, batch_limit)
        print(f"   → {len(results)} result(s)")

        # accumulate new unique results
        for r in results:
            if r["id"] not in seen_ids:
                LoR.append(r)
                seen_ids.add(r["id"])

        print(f"   LoR size now: {len(LoR)}")

        # check stop condition
        if len(LoR) >= target_total:
            print("\n SUCCESS — SUFFICIENT PRIOR ART FOUND")
            print(f"FINAL QUERY: {query}")
            print(f"FINAL LoR SIZE: {len(LoR)}")
            return final_query, LoR

        if len(results) == 0:
            print("   Query too strict — continuing ablation...")
        else:
            print("   Useful results added — continuing...")

    print("\nEND OF BLOCK ELIMINATION— RETURNING BEST AVAILABLE LoR")
    return final_query, LoR
