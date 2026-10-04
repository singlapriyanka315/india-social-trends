-- India Social Trends schema (PostgreSQL)
-- Safe to run many times: everything is CREATE ... IF NOT EXISTS.

-- Where trends come from
CREATE TABLE IF NOT EXISTS sources (
    id      TEXT PRIMARY KEY,                 -- e.g. google_trends_in
    name    TEXT NOT NULL,
    region  TEXT NOT NULL CHECK (region IN ('IN', 'GLOBAL'))
);

-- One row per thing that was trending on a source on a given day
CREATE TABLE IF NOT EXISTS trend_items (
    id            SERIAL PRIMARY KEY,
    source_id     TEXT NOT NULL REFERENCES sources(id),
    trend_date    DATE NOT NULL,
    raw_title     TEXT NOT NULL,                -- exactly as the source gave it
    topic_name    TEXT,                         -- LLM-normalised English name
    category      TEXT,                         -- sports, entertainment, politics, ...
    rank          INT  NOT NULL,                -- 1 = top on that source
    metric        BIGINT,                       -- searches / views / posts, when the source gives one
    metric_label  TEXT,                         -- what metric means for this source
    spike         NUMERIC(8, 2),                -- views vs previous week (Wikipedia only)
    url           TEXT,
    context       TEXT,                         -- related headlines / description
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, trend_date, raw_title)
);
CREATE INDEX IF NOT EXISTS trend_items_date_idx ON trend_items (trend_date);

-- A topic groups items from different sources / days that are about the same thing.
-- Its embedding lives in ChromaDB under the same id.
CREATE TABLE IF NOT EXISTS topics (
    id          SERIAL PRIMARY KEY,
    label       TEXT NOT NULL,
    category    TEXT,
    first_seen  DATE NOT NULL,
    last_seen   DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_items (
    topic_id  INT NOT NULL REFERENCES topics(id),
    item_id   INT NOT NULL REFERENCES trend_items(id) ON DELETE CASCADE,
    distance  NUMERIC(6, 4),                     -- how close the item was to the topic
    PRIMARY KEY (item_id)                        -- each item belongs to one topic
);

-- One row per generated report
CREATE TABLE IF NOT EXISTS reports (
    id           SERIAL PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    report_date  DATE NOT NULL,
    llm_model    TEXT,
    summary      TEXT,
    content_md   TEXT NOT NULL
);

-- Topic ranking inside each report, with the LLM's "why it's trending"
CREATE TABLE IF NOT EXISTS report_topics (
    report_id   INT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    topic_id    INT NOT NULL REFERENCES topics(id),
    region      TEXT NOT NULL,
    position    INT  NOT NULL,
    score       NUMERIC(8, 3) NOT NULL,
    platforms   INT  NOT NULL,
    explanation TEXT,
    PRIMARY KEY (report_id, topic_id)
);
