import asyncio
import logging
from typing import List, Tuple
from prior_art_search import search_openalex


async def search_all_sources(query: str) -> List[dict]:
    """
    Fan-out query to all search engines.

    Engines:
    - OpenAlex (academic papers)
    - PatentsView (patents)
    - Semantic Scholar (academic papers)

    Note: Results are NOT deduplicated across sources to preserve
    paper vs patent separation (user requirement).
    """
    logging.info(f"Searching all sources for: {query[:50]}...")

    # Import search functions
    from prior_art_search import search_patentsview
    from prior_art_search import search_semantic_scholar

    # Dispatch to all engines in parallel
    tasks = [
        search_openalex(query),
        search_patentsview(query),
        search_semantic_scholar(query),
    ]

    logging.info(
        f"Dispatching {len(tasks)} search tasks (OpenAlex + PatentsView + Semantic Scholar)..."
    )

    # Run selected tasks asynchronously
    results_tuple = await asyncio.gather(*tasks, return_exceptions=True)

    combined = []
    source_names = ["OpenAlex", "PatentsView", "Semantic Scholar"]
    for i, res in enumerate(results_tuple):
        name = source_names[i] if i < len(source_names) else f"Source_{i}"
        if isinstance(res, list):
            combined.extend(res)
            logging.info(f"  {name}: {len(res)} results")
        else:
            logging.error(f"  {name}: error — {res}")

    logging.info(f"  Combined: {len(combined)} total prior-art results")
    return combined


def split_ucs(ucs: str) -> List[str]:
    """
    Splits UCS into blocks (AND-separated).
    Same logic as original progressive search.
    """
    blocks = []
    current = []
    depth = 0
    in_quotes = False

    i = 0
    while i < len(ucs):
        ch = ucs[i]

        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "(" and not in_quotes:
            depth += 1
        elif ch == ")" and not in_quotes:
            depth -= 1

        if not in_quotes and depth == 0 and ucs[i : i + 4].upper() == " AND":
            blocks.append("".join(current).strip())
            current = []
            i += 4
            continue

        current.append(ch)
        i += 1

    if current:
        blocks.append("".join(current).strip())
    return blocks


async def progressive_search(ucs: str, target_total: int = 5) -> Tuple[str, List[dict]]:
    """
    Orchestrates the Progressive Search algorithm across ALL engines.

    Strategy:
    1. Try full UCS first.
    2. If results < target, remove ONE top-level AND block at a time (preserving order).
    3. Accumulate unique results across all attempts.
    4. Stop when target is reached or all blocks tested.
    """
    print("\n===== PARALLEL PROGRESSIVE SEARCH ENGINE =====\n")

    # Clean UCS (remove wrapping quotes if present)
    ucs = ucs.strip().strip('"')

    seen_ids = set()
    LoR = []

    # 1. Full Query (ALWAYS TEST FIRST)
    print(f"[FULL QUERY TEST] {ucs[:100]}...")
    results = await search_all_sources(ucs)

    for r in results:
        if r["url"] not in seen_ids:
            LoR.append(r)
            seen_ids.add(r["url"])

    print(f"  -> Found {len(LoR)} unique results.")

    if len(LoR) >= target_total:
        return ucs, LoR

    # 2. Ablation - Remove ONE block at a time
    print("\n[BROADENING SEARCH] Removing blocks one at a time...")
    blocks = split_ucs(ucs)

    if len(blocks) <= 1:
        print("  -> Only 1 block, cannot broaden further.")
        return ucs, LoR

    final_query = ucs

    # Test removing each block individually (in order)
    for i in range(len(blocks)):
        # Skip if we already have enough
        if len(LoR) >= target_total:
            break

        # Construct query with block i removed
        remaining_blocks = blocks[:i] + blocks[i + 1 :]
        if not remaining_blocks:
            continue

        query = " AND ".join(remaining_blocks)
        print(f"\n  [Attempt {i + 1}] Removing block {i + 1}: '{blocks[i][:50]}...'")
        print(f"  Testing: {query[:100]}...")

        new_results = await search_all_sources(query)

        added_count = 0
        for r in new_results:
            if r["url"] not in seen_ids:
                LoR.append(r)
                seen_ids.add(r["url"])
                added_count += 1

        print(f"  -> Added {added_count} new. Total: {len(LoR)}")

        # Update final_query to the last successful broadening
        if added_count > 0:
            final_query = query

    return final_query, LoR
