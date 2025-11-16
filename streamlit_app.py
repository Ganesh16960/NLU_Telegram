import streamlit as st
from typing import List, Dict, Any
import re

# External library for RSS parsing
try:
    import feedparser
except ImportError:
    st.error(
        "The 'feedparser' package is not installed.\n\n"
        "Add this line to your requirements.txt file and redeploy:\n\n"
        "    feedparser"
    )
    st.stop()

# ----------------- Config -----------------

DEFAULT_RSS = [
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
]

WORD_RE = re.compile(r"\w+")


# ----------------- Helper functions -----------------

def text_to_tokens(text: str) -> set:
    return set(w.lower() for w in WORD_RE.findall(text or ""))


def simple_similarity(a: str, b: str) -> float:
    ta, tb = text_to_tokens(a), text_to_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / (len(ta) + len(tb))


def summarize_text(text: str, max_chars: int = 300) -> str:
    """Very simple summary: first few sentences, truncated."""
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    summary = " ".join(sentences[:3])
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "..."
    return summary


def build_rag_summary(
    article: Dict[str, Any],
    history: List[Dict[str, Any]],
    top_k: int = 3,
) -> str:
    """
    Tiny 'RAG-style' summary:
    - Summarize current article
    - Optionally append info about similar past articles
    """
    new_text = (article.get("title", "") + " " + article.get("summary", ""))
    scores = []
    for h in history:
        hist_text = h.get("title", "") + " " + h.get("summary", "")
        sim = simple_similarity(new_text, hist_text)
        scores.append((sim, h))

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
        "summary": getattr(entry, "summary", "")
        or getattr(entry, "description", ""),
        "published": getattr(entry, "published", ""),
    }


# ----------------- Streamlit UI -----------------

st.set_page_config(page_title="RSS → RAG Summaries", page_icon="📰", layout="centered")

st.title("📰 RSS → RAG Summaries")

st.write(
    "Enter one or more RSS feed URLs (one per line). "
    "The app will fetch articles, create short summaries, "
    "and use simple similarity with previous articles as context."
)

rss_input = st.text_area(
    "RSS feed URLs (one per line):",
    value="\n".join(DEFAULT_RSS),
    height=120,
)

max_articles = st.number_input(
    "Max articles to show (per fetch):",
    min_value=1,
    max_value=200,
    value=50,
    step=1,
)

if st.button("Fetch & summarize"):
    urls = [u.strip() for u in rss_input.splitlines() if u.strip()]
    if not urls:
        st.warning("Please enter at least one RSS URL.")
        st.stop()

    all_articles: List[Dict[str, Any]] = []

    with st.spinner("Fetching RSS feeds..."):
        for url in urls:
            st.write(f"🔗 Fetching: `{url}`")
            try:
                feed = feedparser.parse(url)
            except Exception as e:
                st.error(f"Error fetching {url}: {e}")
                continue

            for e in feed.entries:
                all_articles.append(parse_entry(e))

    if not all_articles:
        st.warning("No articles found. Check your RSS URLs.")
        st.stop()

    # Limit number of articles
    all_articles = all_articles[: max_articles]

    # Build RAG-style summaries using previous articles as context
    st.success(f"Fetched {len(all_articles)} articles. Generating summaries...")
    history: List[Dict[str, Any]] = []

    for art in all_articles:
        rag_summary = build_rag_summary(art, history)
        history.append(
            {
                "title": art["title"],
                "summary": rag_summary,
                "link": art["link"],
                "published": art["published"],
            }
        )

    st.subheader("Summaries")

    for a in history:
        st.markdown(f"### {a['title'] or 'Untitled article'}")
        if a.get("published"):
            st.caption(f"Published: {a['published']}")
        st.write(a["summary"] or "_No summary available._")
        if a["link"]:
            st.markdown(f"[Read more]({a['link']})")
        st.write("---")
