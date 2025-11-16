import re
from typing import List, Dict, Any

import streamlit as st
import feedparser
import requests

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


def send_to_telegram(
    articles: List[Dict[str, Any]],
    bot_token: str,
    chat_id: str,
    max_messages: int = 5,
):
    """Send top N articles to Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    count = 0
    for art in articles:
        if count >= max_messages:
            break

        title = art.get("title") or "No title"
        summary = art.get("summary") or ""
        link = art.get("link") or ""

        parts = [f"Title: {title}"]
        if summary:
            parts.append(f"Summary: {summary}")
        if link:
            parts.append(f"Link: {link}")

        text = "\n\n".join(parts)

        resp = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        if not resp.ok:
            st.error(f"Failed to send message {count+1}: {resp.text}")
        else:
            count += 1

    return count


# ----------------- Streamlit UI -----------------

st.set_page_config(page_title="RSS → Telegram RAG", page_icon="📨", layout="centered")

st.title("📨 RSS → Telegram (RAG-style summaries)")

st.write(
    "1) Enter RSS URLs and fetch articles\n"
    "2) Review summaries\n"
    "3) Click **Send to Telegram** to push them with one click"
)

# --- RSS input ---

rss_input = st.text_area(
    "RSS feed URLs (one per line):",
    value="\n".join(DEFAULT_RSS),
    height=120,
)

max_articles = st.number_input(
    "Max articles to fetch:",
    min_value=1,
    max_value=200,
    value=30,
    step=1,
)

max_messages = st.number_input(
    "Max articles to send to Telegram:",
    min_value=1,
    max_value=20,
    value=5,
    step=1,
)

# --- Telegram config ---

st.subheader("Telegram configuration")

# Try to read from secrets if set in Streamlit Cloud
default_bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "") if hasattr(st, "secrets") else ""
default_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "") if hasattr(st, "secrets") else ""

bot_token = st.text_input(
    "Telegram Bot Token",
    value=default_bot_token,
    type="password",
    help="Bot token from @BotFather",
)

chat_id = st.text_input(
    "Telegram Chat ID",
    value=default_chat_id,
    help="Your user / group / channel chat ID",
)

# --- Session state to store fetched articles ---

if "articles" not in st.session_state:
    st.session_state["articles"] = []  # list of dicts with title, summary, link, published


# --- Fetch & summarize button ---

if st.button("🔍 Fetch & summarize"):
    urls = [u.strip() for u in rss_input.splitlines() if u.strip()]
    if not urls:
        st.warning("Please enter at least one RSS URL.")
    else:
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
        else:
            # Limit number of articles
            all_articles = all_articles[: max_articles]

            # Build RAG-style summaries
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

            st.session_state["articles"] = history
            st.success(f"Fetched and summarized {len(history)} articles.")


# --- Show summaries if available ---

articles = st.session_state.get("articles", [])

if articles:
    st.subheader("Preview of articles to send")
    for i, a in enumerate(articles, start=1):
        st.markdown(f"### {i}. {a['title'] or 'Untitled article'}")
        if a.get("published"):
            st.caption(f"Published: {a['published']}")
        st.write(a["summary"] or "_No summary available._")
        if a["link"]:
            st.markdown(f"[Read more]({a['link']})")
        st.write("---")

    # --- Send to Telegram button ---
    if st.button("📨 Send to Telegram"):
        if not bot_token or not chat_id:
            st.error("Please fill in both Telegram Bot Token and Chat ID.")
        else:
            with st.spinner("Sending messages to Telegram..."):
                sent_count = send_to_telegram(
                    articles=articles,
                    bot_token=bot_token,
                    chat_id=chat_id,
                    max_messages=max_messages,
                )

            st.success(f"Sent {sent_count} message(s) to Telegram.")
else:
    st.info("Fetch summaries first, then you can send them to Telegram.")
