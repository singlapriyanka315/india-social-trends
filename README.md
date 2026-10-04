# India Social Trends

A daily pipeline that collects what India (and the world) is talking about online, groups the same story across platforms and languages with vector search, and writes a PDF report explaining why each topic is trending.

**Sample report: [PDF](examples/sample-report.pdf) · [Markdown](examples/sample-report.md)**

```
Google Trends IN ─┐
Wikipedia (IN)  ──┤                 LLM: English name        ChromaDB: group          LLM: why it's
Bluesky         ──┼──► PostgreSQL ──► + category for every ──► same story across ──► trending + summary ──► PDF / .md
Mastodon        ──┤                 item (any language)      platforms and days
Hacker News     ──┘
```

| Layer | Tool | Role |
|---|---|---|
| Data | 5 free public APIs, no keys | What's trending right now |
| Database | PostgreSQL | Source of truth: items, topics, reports |
| Vectors | ChromaDB (local embeddings) | Groups items about the same thing into one topic |
| LLM | Groq free tier, `gpt-oss-120b` | Normalises titles (incl. Hindi, Bengali) to English; explains each topic |
| PDF | ReportLab | Ranked tables, score chart, "why it's trending" cards |

## How it works

1. **Fetch** – top items from each source. Wikipedia uses the *most-read articles from India*, and only keeps
   articles with at least 1.5× their usual views over the previous week, so evergreen pages are filtered out.
2. **Normalise** – the LLM gives every item a short English topic name and a category, and flags noise
   (site pages, bot traffic, evergreen hashtags). This is what lets a Hindi search and an English Wikipedia
   article land in the same topic.
3. **Cluster** – each topic name is embedded in ChromaDB. A new item joins the nearest topic seen in the last
   7 days if the cosine distance is ≤ 0.38, otherwise it starts a new topic. (Measured on real data: same-story
   pairs scored 0.20–0.36, unrelated pairs 0.42+.)
4. **Score & report** – on each platform a topic gets 1.0 for rank #1 down to ~0 for the last item; scores are
   summed across platforms, so cross-platform topics rise to the top. Topics also carry how many days they have
   been trending, and the report lists what faded since the last run.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
createdb social_trends
cp .env.example .env        # add GROQ_API_KEY (free at console.groq.com)
```

## Run

```bash
.venv/bin/python main.py
```

Run it once a day. Re-running on the same day is safe: items are upserted and only new ones are normalised and clustered.
Without a Groq key it still works, using raw titles and no explanations.

## Database

Schema: [`db/schema.sql`](db/schema.sql)

- `sources` – the five platforms and their region (IN / GLOBAL)
- `trend_items` – every trending item per source per day, with raw title, English topic name, category, rank and metric
- `topics` / `topic_items` – the clusters, and which items belong to each (with vector distance)
- `reports` / `report_topics` – every report and how each topic ranked in it

Example queries:

```sql
-- Longest-running topics
SELECT t.label, count(DISTINCT i.trend_date) AS days, min(i.trend_date) AS since
FROM topics t JOIN topic_items ti ON ti.topic_id = t.id JOIN trend_items i ON i.id = ti.item_id
GROUP BY t.id ORDER BY days DESC LIMIT 10;

-- Topics that trended on more than one platform on the same day
SELECT i.trend_date, t.label, array_agg(DISTINCT i.source_id) AS platforms
FROM topics t JOIN topic_items ti ON ti.topic_id = t.id JOIN trend_items i ON i.id = ti.item_id
GROUP BY i.trend_date, t.id HAVING count(DISTINCT i.source_id) > 1 ORDER BY i.trend_date DESC;

-- What India searched for, by category
SELECT category, count(*) FROM trend_items WHERE source_id = 'google_trends_in' GROUP BY 1 ORDER BY 2 DESC;
```

## Project layout

```
main.py              runs the 4 steps
config.py            sources, thresholds, env vars
db/schema.sql        PostgreSQL schema
trends/sources.py    step 1 – the five fetchers
trends/llm.py        step 2 + 4 – normalise, explain, summarise (Groq)
trends/topics.py     step 3 – ChromaDB clustering
trends/db.py         all SQL, including the cross-platform score
trends/report.py     step 4 – ranking, Markdown, saving
trends/pdf.py        step 4 – PDF rendering (ReportLab)
```

## Limitations

- Reddit, X and Instagram have no free public API, and YouTube needs a key, so they aren't included.
- Google Trends' RSS feed gives about 10 items, with approximate search counts ("1000+").
- Bluesky and Mastodon trends are mostly global and English-language.
- Explanations are written by an LLM from headlines only, so check anything important against the source links.
