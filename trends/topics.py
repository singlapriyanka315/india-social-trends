"""Step 3: group items about the same thing into topics, using ChromaDB.

Each topic's name is embedded once. A new item joins the closest topic seen in the
last week if it is close enough (cosine distance below SAME_TOPIC_DISTANCE),
otherwise it starts a new topic. This is how the same story is matched across
platforms today, and across days (so we can say how long something has trended).
"""

from datetime import timedelta

import chromadb

from config import CHROMA_PATH, SAME_TOPIC_DISTANCE
from trends import db


class TopicIndex:
    def __init__(self, path=CHROMA_PATH):
        self.col = chromadb.PersistentClient(path=path).get_or_create_collection(
            "topics", metadata={"hnsw:space": "cosine"}
        )

    def closest(self, text, since_ordinal):
        if self.col.count() == 0:
            return None, None
        res = self.col.query(query_texts=[text], n_results=1,
                             where={"last_seen": {"$gte": since_ordinal}})
        if not res["ids"][0]:
            return None, None
        return int(res["ids"][0][0]), res["distances"][0][0]

    def add(self, topic_id, text, day):
        self.col.upsert(ids=[str(topic_id)], documents=[text],
                        metadatas=[{"last_seen": day.toordinal()}])

    def touch(self, topic_id, day):
        self.col.update(ids=[str(topic_id)], metadatas=[{"last_seen": day.toordinal()}])


def cluster(conn, index, day):
    """Assign every unclustered item from `day` to a topic. Returns (joined, created)."""
    since = (day - timedelta(days=7)).toordinal()
    joined = created = 0
    for it in db.unclustered_items(conn, day):
        text = it["topic_name"] or it["raw_title"]
        topic_id, distance = index.closest(text, since)
        if topic_id is not None and distance <= SAME_TOPIC_DISTANCE:
            index.touch(topic_id, day)
            joined += 1
        else:
            topic_id = db.create_topic(conn, text, it["category"], day)
            index.add(topic_id, text, day)
            distance = 0.0
            created += 1
        db.attach_item(conn, topic_id, it["id"], distance, day)
    conn.commit()
    return joined, created
