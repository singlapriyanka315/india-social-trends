"""
India Social Trends - daily report.

    python main.py

  1. FETCH      Google Trends India, Wikipedia (India), Bluesky, Mastodon, Hacker News -> PostgreSQL
  2. NORMALISE  LLM gives each item an English topic name + category (handles Hindi, Bengali, ...)
  3. CLUSTER    ChromaDB groups items about the same thing into topics, across platforms and days
  4. REPORT     topics ranked by cross-platform score; LLM explains why each is trending
                -> reports/<date>.pdf + .md, and the reports / report_topics tables
"""

import sys
from datetime import date
from pathlib import Path

from config import REPORTS_DIR, SOURCES
from trends import db
from trends.llm import Writer
from trends.sources import FETCHERS
from trends.topics import TopicIndex, cluster

TOP_INDIA = 10
TOP_GLOBAL = 6


def fetch(conn, day):
    for sid, fetcher in FETCHERS.items():
        try:
            items = fetcher()
        except Exception as e:  # one broken source should not stop the report
            print(f"   ! {SOURCES[sid][0]} failed: {e}")
            continue
        db.insert_items(conn, sid, day, items)
        conn.commit()
        print(f"Fetched {SOURCES[sid][0]}: {len(items)} items")


def normalise(conn, writer, day):
    items = db.items_without_topic_name(conn, day)
    if not items:
        return
    if not writer.enabled:  # fallback: use the raw title as the topic name
        for it in items:
            db.set_item_topic_name(conn, it["id"], it["raw_title"], None)
        conn.commit()
        return
    by_source = {}
    for it in items:
        by_source.setdefault(it["source_id"], []).append(it)
    for sid, batch in by_source.items():
        print(f"Normalising {SOURCES[sid][0]}...")
        names = writer.normalise(batch)
        for it in batch:
            name, cat = names.get(it["id"], (it["raw_title"], None))
            db.set_item_topic_name(conn, it["id"], name, cat)
        conn.commit()


def main():
    day = date.today()
    conn = db.connect()
    db.init(conn)
    writer = Writer()
    print("LLM:", writer.model if writer.enabled else "off (set GROQ_API_KEY in .env to enable)")

    fetch(conn, day)
    normalise(conn, writer, day)
    joined, created = cluster(conn, TopicIndex(), day)
    print(f"Clustered: {created} new topics, {joined} items joined an existing topic")

    if "--no-report" in sys.argv:
        return
    from trends.report import build_report
    build_report(conn, writer, day, TOP_INDIA, TOP_GLOBAL, Path(REPORTS_DIR))


if __name__ == "__main__":
    main()
