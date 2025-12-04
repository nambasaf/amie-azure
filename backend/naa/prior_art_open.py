# backend/naa/prior_art_open.py
import requests
import json
import urllib.parse
import logging
import datetime as dt

TIMEOUT = 20  # seconds


# Helper to reconstruct OpenAlex abstract from inverted index
def reconstruct_abstract(inverted_index):
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join(word for pos, word in word_positions)[:400]


# ----------------------------- PatentsView -----------------------------
def pv_search(text, top_k=30):
    """USPTO PatentsView – US patents only, no key needed"""
    query = {"_text_any": {"patent_abstract": text}}
    url = (
        "https://search.patentsview.org/api/patents/query"
        f"?q={json.dumps(query)}"
        f'&f=["patent_number","patent_date","patent_title","patent_abstract"]'
        f'&o={{"per_page":{top_k}}}'
    )
    try:
        r = requests.get(url, timeout=TIMEOUT).json()
        return [
            {
                "patent_id": p["patent_number"],
                "title": p["patent_title"],
                "publication_date": p["patent_date"],
                "snippet": (p.get("patent_abstract") or "")[:400],
                "source": "PatentsView",
            }
            for p in r.get("patents", [])
        ]
    except Exception as e:
        logging.error(f"PatentsView failed: {e}")
        return []


# ----------------------------- OpenAlex -----------------------------
def openalex_search(text, top_k=30):
    """OpenAlex Works – scholarly literature, no key"""
    url = (
        "https://api.openalex.org/works"
        f"?search={urllib.parse.quote_plus(text)}&per_page={top_k}"
    )
    try:
        r = requests.get(url, timeout=TIMEOUT).json()
        return [
            {
                "paper_id": w["id"].split("/")[-1],  # Extract ID for consistency
                "title": w["display_name"],
                "publication_date": w.get("publication_year", "1900") + "-01-01",
                "snippet": reconstruct_abstract(w.get("abstract_inverted_index")),
                "source": "OpenAlex",
            }
            for w in r.get("results", [])
        ]
    except Exception as e:
        logging.error(f"OpenAlex failed: {e}")
        return []


# ----------------------------- Semantic Scholar -----------------------------
def semscholar_search(text, top_k=30):
    """Semantic Scholar – add &fields=abstract to get full abstract"""
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={urllib.parse.quote_plus(text)}"
        f"&limit={top_k}"
        "&fields=title,abstract,year,publicationDate"
    )
    try:
        r = requests.get(url, timeout=TIMEOUT).json()
        return [
            {
                "paper_id": p["paperId"],
                "title": p["title"],
                "publication_date": p.get("publicationDate")
                or f"{p.get('year', 1900)}-01-01",
                "snippet": (p.get("abstract") or "")[:400],
                "source": "SemanticScholar",
            }
            for p in r.get("data", [])
        ]
    except Exception as e:
        logging.error(f"Semantic Scholar failed: {e}")
        return []


def search_prior_art(query_text: str) -> list:
    """Aggregate three open endpoints; deduplicate by title."""
    results = (
        pv_search(query_text)
        + openalex_search(query_text)
        + semscholar_search(query_text)
    )
    seen = set()
    deduped = []
    for r in results:
        title_key = (r.get("title") or "").lower().strip()
        if title_key and title_key not in seen:
            seen.add(title_key)
            deduped.append(r)
    return deduped[:15]  # cap total results
