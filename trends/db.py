"""All PostgreSQL access lives here."""

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from config import DATABASE_URL, SOURCES

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def connect():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init(conn):
    conn.execute(SCHEMA.read_text())
    for sid, (name, region) in SOURCES.items():
        conn.execute(
            "INSERT INTO sources (id, name, region) VALUES (%s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, region = EXCLUDED.region",
            (sid, name, region),
        )
    conn.commit()


# ---------------------------------------------------------------- items
def insert_items(conn, source_id, trend_date, items):
    """Insert today's items for a source. Re-running the same day updates rank/metric."""
    ids = []
    for it in items:
        row = conn.execute(
            """
            INSERT INTO trend_items (source_id, trend_date, raw_title, rank, metric, metric_label,
                                     spike, url, context)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, trend_date, raw_title) DO UPDATE SET
                rank = EXCLUDED.rank, metric = EXCLUDED.metric, spike = EXCLUDED.spike,
                url = EXCLUDED.url, context = EXCLUDED.context, fetched_at = now()
            RETURNING id
            """,
            (source_id, trend_date, it["raw_title"], it["rank"], it.get("metric"),
             it.get("metric_label"), it.get("spike"), it.get("url"), it.get("context")),
        ).fetchone()
        ids.append(row["id"])
    return ids


def items_without_topic_name(conn, trend_date):
    return conn.execute(
        """
        SELECT id, source_id, raw_title, context FROM trend_items
        WHERE trend_date = %s AND topic_name IS NULL ORDER BY source_id, rank
        """,
        (trend_date,),
    ).fetchall()


def set_item_topic_name(conn, item_id, topic_name, category):
    conn.execute("UPDATE trend_items SET topic_name = %s, category = %s WHERE id = %s",
                 (topic_name, category, item_id))


def unclustered_items(conn, trend_date):
    return conn.execute(
        """
        SELECT i.* FROM trend_items i
        LEFT JOIN topic_items ti ON ti.item_id = i.id
        WHERE i.trend_date = %s AND ti.item_id IS NULL AND coalesce(i.category, '') <> 'noise'
        ORDER BY i.rank, i.source_id
        """,
        (trend_date,),
    ).fetchall()


# ---------------------------------------------------------------- topics
def create_topic(conn, label, category, day):
    return conn.execute(
        "INSERT INTO topics (label, category, first_seen, last_seen) VALUES (%s, %s, %s, %s) RETURNING id",
        (label, category, day, day),
    ).fetchone()["id"]


def attach_item(conn, topic_id, item_id, distance, day):
    conn.execute(
        "INSERT INTO topic_items (topic_id, item_id, distance) VALUES (%s, %s, %s) "
        "ON CONFLICT (item_id) DO NOTHING",
        (topic_id, item_id, distance),
    )
    conn.execute("UPDATE topics SET last_seen = greatest(last_seen, %s) WHERE id = %s", (day, topic_id))


def ranked_topics(conn, day):
    """
    Score each topic seen today: for every source it appears on, take its best rank
    on that source and turn it into 0..1 (rank 1 = 1.0), then add them up.
    A topic that is #1 on two platforms beats one that is #1 on only one.
    """
    return conn.execute(
        """
        WITH per_source AS (
            SELECT ti.topic_id, i.source_id, min(i.rank) AS best_rank,
                   (SELECT count(*) FROM trend_items x
                    WHERE x.source_id = i.source_id AND x.trend_date = %(day)s) AS n
            FROM topic_items ti JOIN trend_items i ON i.id = ti.item_id
            WHERE i.trend_date = %(day)s
            GROUP BY ti.topic_id, i.source_id
        ),
        days AS (
            SELECT ti.topic_id, count(DISTINCT i.trend_date) AS days_trending
            FROM topic_items ti JOIN trend_items i ON i.id = ti.item_id
            GROUP BY ti.topic_id
        )
        SELECT t.id, t.label, t.category, t.first_seen,
               sum((p.n - p.best_rank + 1)::numeric / p.n) AS score,
               count(*) AS platforms,
               array_agg(p.source_id ORDER BY p.best_rank) AS source_ids,
               bool_or(s.region = 'IN') AS in_india,
               d.days_trending
        FROM per_source p
        JOIN topics t ON t.id = p.topic_id
        JOIN sources s ON s.id = p.source_id
        JOIN days d ON d.topic_id = t.id
        GROUP BY t.id, d.days_trending
        ORDER BY score DESC
        """,
        {"day": day},
    ).fetchall()


def topic_items_on(conn, topic_id, day):
    return conn.execute(
        """
        SELECT i.*, s.name AS source_name FROM topic_items ti
        JOIN trend_items i ON i.id = ti.item_id JOIN sources s ON s.id = i.source_id
        WHERE ti.topic_id = %s AND i.trend_date = %s ORDER BY i.rank
        """,
        (topic_id, day),
    ).fetchall()


def previous_report_topics(conn, before_day, region):
    """Topics from the most recent earlier report, to find what has faded."""
    return conn.execute(
        """
        SELECT rt.topic_id, t.label, r.report_date FROM report_topics rt
        JOIN reports r ON r.id = rt.report_id JOIN topics t ON t.id = rt.topic_id
        WHERE r.id = (SELECT max(id) FROM reports WHERE report_date < %s) AND rt.region = %s
        ORDER BY rt.position
        """,
        (before_day, region),
    ).fetchall()


# ---------------------------------------------------------------- reports
def save_report(conn, day, llm_model, summary, content_md, ranked):
    """ranked: list of dicts with topic_id, region, position, score, platforms, explanation"""
    rid = conn.execute(
        "INSERT INTO reports (report_date, llm_model, summary, content_md) VALUES (%s, %s, %s, %s) RETURNING id",
        (day, llm_model, summary, content_md),
    ).fetchone()["id"]
    for r in ranked:
        conn.execute(
            """
            INSERT INTO report_topics (report_id, topic_id, region, position, score, platforms, explanation)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (rid, r["topic_id"], r["region"], r["position"], r["score"], r["platforms"], r.get("explanation")),
        )
    return rid
