import os
import json
import re
from typing import List, Dict, Any
from datetime import datetime

import feedparser
import requests

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
RSS_FEEDS = os.environ.get("RSS_FEEDS", "").split() or [
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
]

MAX_TELEGRAM_MESSAGES_PER_RUN = int(os.environ.get("MAX_MESSAGES", "5"))
STATE_FILE = "rss_state.json"

WORD_RE = re.compile(r"\w+")


def load_state(path: str = STATE_FILE) -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen_ids": [], "articles": []}


def save_state(state: Dict[str, Any], path: str = STATE_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


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
        summary = summary[: max_chars].rstrip() + "..."
    return summary


def build_rag_summary(article: Dict[str, Any],
                      context_articles: List[Dict[str, Any]]) -> str:
    new_text = (article.get("title", "") + " " +
                article.get("summary", ""))
    scores = []
    for h in context_articles:
        hist_text = h.get("title", "") + " " + h.get("summary", "")
        scores.append((simple_similarity(new_text, hist_text), h))
    scores.sort(key=lambda x: x[0], reverse=True)
    ctx = [h for sim, h in scores[:3] if sim > 0]

    base_summary = summarize_text(article.get("summary", ""))
    if not ctx:
        return base_summary
    rel_titles = [c.get("title", "") for c in ctx if c.get("title")]
    if rel_titles:
        extra = "Related to: " + "; ".join(rel_titles[:2])
        if len(base_summary) + len(extra) + 3 < 350:
            return base_summary + " | " + extra
    return base_summary


def extract_entry_id(entry: Any) -> str:
    return (getattr(entry, "id", None)
            or getattr(entry, "link", None)
            or (getattr(entry, "title", "") + getattr(entry, "published", "")))


def parse_entry(entry: Any) -> Dict[str, Any]:
    return {
        "id": extract_entry_id(entry),
        "title": getattr(entry, "title", ""),
        "link": getattr(entry, "link", ""),
        "summary": getattr(entry, "summary", "") or getattr(entry, "description", ""),
        "published": getattr(entry, "published", ""),
    }


def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, data=payload)
    if not resp.ok:
        print("Failed to send message:", resp.text)


def fetch_new_articles() -> List[Dict[str, Any]]:
    new_articles = []
    for url in RSS_FEEDS:
        print("Fetching:", url)
        feed = feedparser.parse(url)
        for entry in feed.entries:
            new_articles.append(parse_entry(entry))
    return new_articles


def run_rss_to_telegram():
    state = load_state()
    seen_ids = set(state.get("seen_ids", []))
    history = state.get("articles", [])

    all_new = fetch_new_articles()
    unseen = [a for a in all_new if a["id"] not in seen_ids]

    if not unseen:
        print("No new articles.")
        return

    def parse_pub(a):
        return a.get("published", "") or ""
    unseen.sort(key=parse_pub, reverse=True)

    count_sent = 0
    for article in unseen:
        if count_sent >= MAX_TELEGRAM_MESSAGES_PER_RUN:
            break

        rag_summary = build_rag_summary(article, history)
        title = article.get("title", "").strip()
        link = article.get("link", "").strip()

        msg_lines = []
        if title:
            msg_lines.append(f"Title: {title}")
        if rag_summary:
            msg_lines.append(f"Summary: {rag_summary}")
        if link:
            msg_lines.append(f"Link: {link}")
        message = "\n\n".join(msg_lines)

        print("Sending:\n", message, "\n---")
        send_telegram_message(message)

        seen_ids.add(article["id"])
        history.append({
            "id": article["id"],
            "title": title,
            "summary": rag_summary,
            "link": link,
            "published": article.get("published", ""),
            "sent_at": datetime.utcnow().isoformat(),
        })
        count_sent += 1

    state["seen_ids"] = list(seen_ids)
    state["articles"] = history
    save_state(state)
    print(f"Done. Sent {count_sent} messages.")


if __name__ == "__main__":
    run_rss_to_telegram()
