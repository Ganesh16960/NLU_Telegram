import streamlit as st
import feedparser
from typing import List, Dict, Any
import re

DEFAULT_RSS = [
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
]

WORD_RE = re.compile(r"\w+")


def text_to_tokens(text: str) -> set:
    return set(w.lower() for w in WORD_RE.findall(text or ""))


def simple_similarity(a: str, b: str) -> float:
    ta, tb = text_to_tokens(a), text_to_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / (len(ta) + len(tb))


def summarize_text(text: str, max_chars: int = 300) -> str:
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    summary = " ".join(sentences[:3])
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "..."
    return summary


def build_rag_summary(article: Dict[str, Any],
                      history: List[Dict[str, Any]],
                      top_k: int = 3) -> str:
    new_text = (article.get("title", "") + " " +
                article.get("summary", ""))
    scores = []
    for h in history:
        hist_text = h.get("title", "") + " " + h.get("summary", "")
        scores.append((simple_similarity(new_text, hist_text), h))
    scores.sort(key=lambda x: x[0], reverse=True)
    context = [h for sim, h in scores[:top_k] if sim > 0]

    base_summary = summarize_text(article.get("summary", ""))
    if not context:
        return base_summary
    rel_titles = [c.get("title", "") for c in context if c.get("title")]
    if rel_titles:
        ctx = "Related to: " + "; ".join(rel_titles[:2])
        if len(base_summary) + len(ctx) + 3 < 350:
            return base_summary + " | " + ctx
    return base_summary


def parse_entry(entry: Any) -> Dict[str, Any]:
    return {
        "title": getattr(entry, "title", ""),
        "link": getattr(entry, "link", ""),
        "summary": getattr(entry, "summary", "") or getattr(entry, "description", ""),
        "published": getattr(entry, "published", ""),
    }


st.title("RSS → RAG Summaries")

rss_input = st.text_area(
    "RSS feed URLs (one per line)",
    value="\n".join(DEFAULT_RSS),
    height=120
)

if st.button("Fetch & summarize"):
    urls = [u.strip() for u in rss_input.splitlines() if u.strip()]
    all_articles: List[Dict[str, Any]] = []
    for url in urls:
        st.write(f"Fetching: {url}")
        feed = feedparser.parse(url)
        for e in feed.entries:
            all_articles.append(parse_entry(e))

    history: List[Dict[str, Any]] = []
    for art in all_articles:
        rag_summary = build_rag_summary(art, history)
        history.append({
            "title": art["title"],
            "summary": rag_summary,
            "link": art["link"],
            "published": art["published"],
        })

    st.subheader("Summaries")
    for a in history:
        st.markdown(f"### {a['title']}")
        st.write(a["summary"])
        if a["link"]:
            st.markdown(f"[Read more]({a['link']})")
        st.write("---")
