"""Step 1: fetch what is trending right now. Every source here is free and needs no API key.

Each fetcher returns a list of dicts:
    raw_title, rank, metric, metric_label, url, context, spike (optional)
"""

import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

from config import ITEMS_PER_SOURCE, USER_AGENT, WIKI_SPIKE_MIN

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT


def _get(url, **kw):
    r = session.get(url, timeout=30, **kw)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------- Google Trends (India)
GT_NS = {"ht": "https://trends.google.com/trending/rss"}


def _parse_traffic(text):
    """'2,000+' -> 2000, '10K+' -> 10000, '1M+' -> 1000000"""
    m = re.match(r"([\d,.]+)\s*([KkMm]?)", text or "")
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return int(n * {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1))


def google_trends_in():
    root = ET.fromstring(_get("https://trends.google.com/trending/rss?geo=IN").content)
    items = []
    for i, it in enumerate(root.iter("item"), start=1):
        news = it.findall("ht:news_item", GT_NS)
        headlines = [n.findtext("ht:news_item_title", "", GT_NS) for n in news]
        traffic = it.findtext("ht:approx_traffic", "", GT_NS)
        items.append({
            "raw_title": it.findtext("title", "").strip(),
            "rank": i,
            "metric": _parse_traffic(traffic),
            "metric_label": "searches",
            "url": news[0].findtext("ht:news_item_url", "", GT_NS) if news else None,
            "context": " | ".join(h for h in headlines if h)[:600],
        })
    return items[:ITEMS_PER_SOURCE]


# ---------------------------------------------------------------- Wikipedia, read from India
WIKI_TOP_IN = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top-per-country/IN/all-access/{d:%Y/%m/%d}"
NOT_ARTICLES = {"special", "wikipedia", "file", "category", "portal", "help", "template", "user",
                "talk", "draft", "विशेष", "विकिपीडिया", "चित्र", "श्रेणी", "সম্মনিত", "বিশেষ"}
MAIN_PAGES = {"main_page", "मुखपृष्ठ", "প্রধান_পাতা", "முதற்_பக்கம்", "మొదటి_పేజీ", "मुख्यपृष्ठ"}


def _wiki_top(day):
    r = session.get(WIKI_TOP_IN.format(d=day), timeout=30)
    if r.status_code == 404:  # that day isn't published yet
        return None
    r.raise_for_status()
    return r.json()["items"][0]["articles"]


def _is_article(name):
    prefix = name.split(":", 1)[0].lower() if ":" in name else ""
    return name.lower() not in MAIN_PAGES and prefix not in NOT_ARTICLES and not prefix.endswith("talk")


def wikipedia_in():
    # Latest published day (usually yesterday)
    day = date.today() - timedelta(days=1)
    today = _wiki_top(day)
    if today is None:
        day -= timedelta(days=1)
        today = _wiki_top(day)

    # Baseline: views in the previous 7 days, to separate spikes from always-popular pages
    history = {}
    for back in range(1, 8):
        for a in _wiki_top(day - timedelta(days=back)) or []:
            history.setdefault((a["project"], a["article"]), []).append(a["views_ceil"])

    items = []
    for a in today:
        if not _is_article(a["article"]):
            continue
        past = history.get((a["project"], a["article"]), [])
        # Missing from the top list on a day means it had fewer views than the list cut-off;
        # count those days as 0 so a page that just appeared gets a big spike.
        baseline = sum(past) / 7
        spike = a["views_ceil"] / baseline if baseline else None  # None = brand new
        if spike is not None and spike < WIKI_SPIKE_MIN:
            continue
        items.append({
            "raw_title": a["article"].replace("_", " "),
            "metric": a["views_ceil"],
            "metric_label": f"views on {day:%d %b}",
            "spike": round(spike, 2) if spike else None,
            "url": f"https://{a['project']}.org/wiki/{a['article']}",
            "context": f"{a['project']} article",
        })
        if len(items) == ITEMS_PER_SOURCE:
            break
    for i, it in enumerate(items, start=1):
        it["rank"] = i
    return items


# ---------------------------------------------------------------- Bluesky
def bluesky():
    data = _get("https://public.api.bsky.app/xrpc/app.bsky.unspecced.getTrendingTopics").json()
    return [{
        "raw_title": t["topic"],
        "rank": i,
        "metric": None,
        "metric_label": None,
        "url": "https://bsky.app" + t["link"] if t.get("link", "").startswith("/") else t.get("link"),
        "context": t.get("description") or "",
    } for i, t in enumerate(data.get("topics", [])[:ITEMS_PER_SOURCE], start=1)]


# ---------------------------------------------------------------- Mastodon
def mastodon():
    half = ITEMS_PER_SOURCE // 2
    links = _get(f"https://mastodon.social/api/v1/trends/links?limit={half}").json()
    tags = _get(f"https://mastodon.social/api/v1/trends/tags?limit={half}").json()
    items = []
    for l in links:  # shared news stories
        items.append({
            "raw_title": l["title"],
            "metric": int(l["history"][0]["uses"]) if l.get("history") else None,
            "metric_label": "shares today",
            "url": l["url"],
            "context": f"{l.get('provider_name', '')}: {l.get('description', '')}"[:600],
        })
    for t in tags:  # hashtags
        items.append({
            "raw_title": "#" + t["name"],
            "metric": int(t["history"][0]["uses"]) if t.get("history") else None,
            "metric_label": "posts today",
            "url": t["url"],
            "context": "Mastodon hashtag",
        })
    for i, it in enumerate(items, start=1):
        it["rank"] = i
    return items


# ---------------------------------------------------------------- Hacker News
def hackernews():
    ids = _get("https://hacker-news.firebaseio.com/v0/topstories.json").json()[:ITEMS_PER_SOURCE]
    items = []
    for i, sid in enumerate(ids, start=1):
        s = _get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json").json() or {}
        if not s.get("title"):
            continue
        items.append({
            "raw_title": s["title"],
            "rank": i,
            "metric": s.get("score"),
            "metric_label": "points",
            "url": s.get("url") or f"https://news.ycombinator.com/item?id={sid}",
            "context": "Hacker News story",
        })
    return items


FETCHERS = {
    "google_trends_in": google_trends_in,
    "wikipedia_in": wikipedia_in,
    "bluesky": bluesky,
    "mastodon": mastodon,
    "hackernews": hackernews,
}
