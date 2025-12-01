# backend/naa/prior_art_open.py
import requests, json, urllib.parse, logging, datetime as dt

TIMEOUT = 20  # seconds


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
                "snippet": p.get("patent_abstract", "")[:400],
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
                "paper_id": w["id"],
                "title": w["display_name"],
                "publication_date": w.get("publication_date", "1900-01-01"),
                "snippet": (w.get("abstract_inverted_index") or {})
                .keys()
                .__iter__()
                .__next__()
                if w.get("abstract_inverted_index")
                else "",
                "source": "OpenAlex",
            }
            for w in r.get("results", [])
        ]
    except Exception as e:
        logging.error(f"OpenAlex failed: {e}")
        return []


#
# ----------------------------- Semantic Scholar -----------------------------
def semscholar_search(text, top_k=30):
    """Semantic Scholar – 100 req/day without key"""
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={urllib.parse.quote_plus(text)}"
        f"&limit={top_k}"
        "&fields=title,abstract,year,publicationDate,url"
    )
    try:
        r = requests.get(url, timeout=TIMEOUT).json()
        return [
            {
                "paper_id": p["paperId"],
                "title": p["title"],
                "publication_date": p.get("publicationDate")
                or f"{p.get('year', 0)}-01-01",
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
        title_key = r["title"].lower() if r.get("title") else ""
        if title_key and title_key not in seen:
            seen.add(title_key)
            deduped.append(r)
    return deduped[:15]  # cap total results
