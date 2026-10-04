"""LLM steps via Groq's free tier. Every step has a no-LLM fallback."""

import json
import time

from groq import APIConnectionError, APIStatusError, RateLimitError

from config import GROQ_API_KEY, GROQ_MODEL

CATEGORIES = ["sports", "entertainment", "politics", "business", "technology",
              "science", "world", "society", "noise"]


class Writer:
    def __init__(self):
        self.model = GROQ_MODEL if GROQ_API_KEY else None
        self.client = None
        if GROQ_API_KEY:
            from groq import Groq
            self.client = Groq(api_key=GROQ_API_KEY)

    @property
    def enabled(self):
        return self.client is not None

    def ask(self, prompt, as_json=False, retries=3):
        extra = {}
        if "gpt-oss" in self.model:
            # reasoning models can spend the whole reply "thinking" and return no text
            extra = {"reasoning_effort": "low", "include_reasoning": False}
        if as_json:
            extra["response_format"] = {"type": "json_object"}
        for attempt in range(retries):
            try:
                r = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    **extra,
                )
                time.sleep(2)  # stay under free-tier rate limits
                text = (r.choices[0].message.content or "").strip()
                if not text:
                    print("   LLM returned an empty reply, retrying...")
                    continue
                return json.loads(text) if as_json else text
            except json.JSONDecodeError:
                print("   LLM returned invalid JSON, retrying...")
            except (RateLimitError, APIConnectionError) as e:  # temporary - worth retrying
                print(f"   LLM busy ({e.__class__.__name__}), retrying...")
                time.sleep(5 * (attempt + 1))
            except APIStatusError as e:  # bad model, bad key, ... - retrying won't help
                print(f"   LLM error: {e.message}")
                return None
        return None

    # ------------------------------------------------------------ step 2: normalise
    def normalise(self, items):
        """
        Give every raw trend a short English topic name and a category, so that
        'barcelona vs real madrid', 'El Clásico' and a Hindi headline all end up
        with similar names - which is what makes vector clustering work across
        languages and platforms.
        Returns {item_id: (topic_name, category)}.
        """
        listing = "\n".join(
            f'{it["id"]}: "{it["raw_title"]}" (context: {(it["context"] or "")[:200]})' for it in items
        )
        out = self.ask(
            "Below are things trending online today, from different platforms and languages.\n"
            "For each one return a short English topic name (2-8 words) that names the real-world "
            "event, person, film, match etc. Use the same name for items about the same thing. "
            "Translate non-English titles. Pick a category from: " + ", ".join(CATEGORIES) + ". "
            "Use 'noise' for site pages, bot traffic, adult content, or evergreen hashtags with no news "
            "(e.g. #Caturday, #SilentSunday).\n\n"
            f"{listing}\n\n"
            'Reply as JSON: {"items": [{"id": <id>, "topic": "...", "category": "..."}]}',
            as_json=True,
        )
        result = {}
        for row in (out or {}).get("items", []):
            try:
                cat = row.get("category", "society")
                result[int(row["id"])] = (row["topic"].strip(), cat if cat in CATEGORIES else "society")
            except (KeyError, ValueError, AttributeError):
                continue
        return result

    # ------------------------------------------------------------ step 4: explain
    def explain(self, topics):
        """topics: list of {id, label, evidence}. Returns {topic_id: (better_label, why)}."""
        listing = "\n\n".join(f'Topic {t["id"]}: {t["label"]}\nEvidence:\n{t["evidence"]}' for t in topics)
        out = self.ask(
            "For each trending topic below, using ONLY the evidence given, write:\n"
            "- label: a clear headline-style name (max 8 words)\n"
            "- why: 1-2 sentences on why it is trending today. If the evidence does not say why, "
            "say what it is and that the reason is unclear. Do not invent facts, scores or dates.\n\n"
            f"{listing}\n\n"
            'Reply as JSON: {"topics": [{"id": <id>, "label": "...", "why": "..."}]}',
            as_json=True,
        )
        result = {}
        for row in (out or {}).get("topics", []):
            try:
                result[int(row["id"])] = (row["label"].strip(), row["why"].strip())
            except (KeyError, ValueError, AttributeError):
                continue
        return result

    def summary(self, facts):
        return self.ask(
            "Write a 4-5 sentence summary of what India is talking about online today, for a daily "
            "trends report, then one sentence on the biggest global trend. Use only these facts. "
            "Lead with topics on 2+ platforms if there are any; never say a topic is on several "
            "platforms or sources unless its platform count is 2 or more. Don't call a trend new or "
            "long-running unless the day count says so. Do not quote any numbers (search counts, views, points) and do not claim one topic is bigger than another - the table shows that. No hype.\n\n" + facts
        )
