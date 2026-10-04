"""Step 4: rank topics, ask the LLM why they are trending, write Markdown + PDF, save to Postgres."""

from config import SOURCES
from trends import db
from trends.pdf import render_pdf

DISCLAIMER = "Automatically generated from public trend data; explanations are AI-written from headlines"

SHORT = {
    "google_trends_in": "Google",
    "wikipedia_in": "Wikipedia",
    "bluesky": "Bluesky",
    "mastodon": "Mastodon",
    "hackernews": "Hacker News",
}


def _evidence(items):
    lines = []
    for i in items[:4]:
        metric = f", {i['metric']:,} {i['metric_label']}" if i["metric"] and i["metric_label"] else ""
        spike = f", {i['spike']}x usual views" if i["spike"] else ""
        lines.append(f"- {i['source_name']} #{i['rank']}: {i['raw_title']}{metric}{spike}. "
                     f"{(i['context'] or '')[:300]}")
    return "\n".join(lines)


def _pick(conn, day, top_india, top_global):
    ranked = db.ranked_topics(conn, day)
    # On the very first run everything is "new", which says nothing - only flag new once there is history
    has_history = conn.execute("SELECT 1 FROM trend_items WHERE trend_date < %s LIMIT 1", (day,)).fetchone()
    india = [t for t in ranked if t["in_india"]][:top_india]
    world = [t for t in ranked if not t["in_india"]][:top_global]
    for region, group in (("IN", india), ("GLOBAL", world)):
        for pos, t in enumerate(group, start=1):
            items = db.topic_items_on(conn, t["id"], day)
            t.update(region=region, position=pos, items=items, evidence=_evidence(items),
                     platforms_list=[SHORT[s] for s in t["source_ids"]],
                     is_new=bool(has_history) and t["first_seen"] == day, explanation=None,
                     top_link=next((i["url"] for i in items if i["url"]), None))
    return india, world


def _faded(conn, day, current_ids):
    return [p for p in db.previous_report_topics(conn, day, "IN") if p["topic_id"] not in current_ids]


def render_md(day, india, world, faded, summary):
    out = [f"# India Social Trends", f"_{day:%A, %d %b %Y} · {DISCLAIMER}_\n"]
    if summary:
        out += ["## Summary\n", summary + "\n"]

    for title, group in (("Top in India", india), ("Global", world)):
        out += [f"## {title}\n", "| # | Topic | Category | Platforms | Days | Score |",
                "|---:|---|---|---|---:|---:|"]
        for t in group:
            new = " 🆕" if t["is_new"] else ""
            out.append(f"| {t['position']} | {t['label']}{new} | {t['category'] or '-'} | "
                       f"{', '.join(t['platforms_list'])} | {t['days_trending']} | {t['score']:.2f} |")
        out.append("")
        for t in group:
            out.append(f"### {t['position']}. {t['label']}\n")
            if t["explanation"]:
                out.append(t["explanation"] + "\n")
            out += [f"- {i['source_name']} #{i['rank']}: [{i['raw_title']}]({i['url']})" for i in t["items"][:4]]
            out.append("")

    if faded:
        out += ["## Fading since last report\n"] + [f"- {f['label']}" for f in faded] + [""]

    out += ["---", "**Score**: for each platform a topic appears on, rank #1 = 1.0 down to the last item ≈ 0; "
            "scores are added across platforms, so cross-platform topics rise to the top.",
            "**Sources**: " + ", ".join(name for name, _ in SOURCES.values())]
    return "\n".join(out)


def build_report(conn, writer, day, top_india, top_global, reports_dir):
    india, world = _pick(conn, day, top_india, top_global)
    if not india and not world:
        print("No topics for today - nothing to report.")
        return

    summary = None
    if writer.enabled:
        print("Explaining topics...")
        explained = writer.explain([{"id": t["id"], "label": t["label"], "evidence": t["evidence"]}
                                    for t in india + world])
        for t in india + world:
            if t["id"] in explained:
                t["label"], t["explanation"] = explained[t["id"]]
        print("Writing summary...")
        facts = "\n".join(
            f"[{t['region']}] {t['label']} ({t['category']}; on {t['platforms']} platform(s): "
            f"{', '.join(t['platforms_list'])}; trending {t['days_trending']} day(s)): {t['explanation'] or ''}"
            for t in india + world)
        summary = writer.summary(facts)

    faded = _faded(conn, day, {t["id"] for t in india})
    content = render_md(day, india, world, faded, summary)
    rid = db.save_report(conn, day, writer.model, summary, content, [
        {"topic_id": t["id"], "region": t["region"], "position": t["position"], "score": t["score"],
         "platforms": t["platforms"], "explanation": t["explanation"]} for t in india + world])
    conn.commit()

    reports_dir.mkdir(exist_ok=True)
    md_path = reports_dir / f"social-trends-{day:%Y-%m-%d}.md"
    md_path.write_text(content)
    pdf_path = md_path.with_suffix(".pdf")
    render_pdf(pdf_path, day, india, world, faded, summary, DISCLAIMER)
    print(f"\nDone → {pdf_path}\n       {md_path}  (saved as report #{rid} in Postgres)")
