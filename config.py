import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/social_trends")
CHROMA_PATH = os.environ.get("CHROMA_PATH", "./vector_db")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")  # check console.groq.com if retired
REPORTS_DIR = "reports"

# Some APIs (Wikimedia) ask for a descriptive User-Agent
USER_AGENT = "india-social-trends/1.0 (learning project; https://github.com/singlapriyanka315)"

# id: (display name, region)
SOURCES = {
    "google_trends_in": ("Google Trends India", "IN"),
    "wikipedia_in":     ("Wikipedia (read from India)", "IN"),
    "bluesky":          ("Bluesky", "GLOBAL"),
    "mastodon":         ("Mastodon", "GLOBAL"),
    "hackernews":       ("Hacker News", "GLOBAL"),
}

ITEMS_PER_SOURCE = 20

# Topic clustering: cosine distance below this = same topic (0 = identical, 1 = unrelated).
# Measured on real data: same-story pairs scored 0.20-0.36, unrelated pairs 0.42+.
SAME_TOPIC_DISTANCE = 0.38

# Wikipedia: only count an article as trending if today's views are this many
# times its average over the previous week (or it was not in the top list at all)
WIKI_SPIKE_MIN = 1.5
