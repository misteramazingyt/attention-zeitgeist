"""Rule-based classification of domains, Wikipedia articles, and subreddits.

This is a deliberately simple, transparent first pass: keyword and known-domain
rules map entities onto the project's default category taxonomy and a coarse
``topic`` label. The design leaves a clean seam for swapping in ML classifiers
later (e.g. zero-shot or embedding-based) without changing the call sites.

Three public entry points mirror the CLI:

* :func:`classify_domains`   -> labels the ``domains`` table.
* :func:`classify_wikipedia` -> labels Wikipedia article entities.
* :func:`classify_reddit`    -> labels subreddit entities.

All three write into the ``entity_classification`` table (and, for domains,
also the ``domains.category_label`` / ``platform_label`` columns).
"""

from __future__ import annotations

from ..schemas import DEFAULT_CATEGORIES
from ..storage import Storage
from ..utils.logging import get_logger

logger = get_logger(__name__)

# --- Known platform domains ------------------------------------------------
PLATFORM_LABELS: dict[str, str] = {
    "youtube.com": "YouTube",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "x.com": "X/Twitter",
    "twitter.com": "X/Twitter",
    "reddit.com": "Reddit",
    "twitch.tv": "Twitch",
    "discord.com": "Discord",
    "linkedin.com": "LinkedIn",
    "wikipedia.org": "Wikipedia",
    "github.com": "GitHub",
    "netflix.com": "Netflix",
    "spotify.com": "Spotify",
}

# --- Known-domain -> category overrides (highest precedence) ---------------
DOMAIN_CATEGORY: dict[str, str] = {
    "nytimes.com": "news", "bbc.com": "news", "cnn.com": "news",
    "theguardian.com": "news", "reuters.com": "news", "apnews.com": "news",
    "foxnews.com": "news", "washingtonpost.com": "news", "aljazeera.com": "news",
    "bloomberg.com": "finance",
    "youtube.com": "entertainment", "netflix.com": "entertainment",
    "tiktok.com": "social media", "instagram.com": "social media",
    "facebook.com": "social media", "x.com": "social media",
    "twitter.com": "social media", "linkedin.com": "social media",
    "reddit.com": "forums",
    "espn.com": "sports",
    "twitch.tv": "gaming",
    "github.com": "technology", "openai.com": "AI",
    "wikipedia.org": "reference",
    "amazon.com": "commerce",
    "pornhub.com": "pornography", "xvideos.com": "pornography",
    "google.com": "technology", "bing.com": "technology", "yahoo.com": "technology",
    "apple.com": "technology", "microsoft.com": "technology",
    "spotify.com": "entertainment",
}

# --- Keyword rules (substring match, ordered by specificity) ----------------
# Each tuple is (category, [keywords]). Earlier entries win on ties.
KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("AI", ["artificial intelligence", "machine learning", "chatgpt", "openai",
            "llm", "large language model", "neural network", "deep learning"]),
    ("politics", ["election", "president", "senate", "congress", "parliament",
                  "government", "minister", "trump", "biden", "putin", "policy",
                  "democrat", "republican", "war", "ukraine", "israel", "gaza"]),
    ("religion", ["buddhism", "christianity", "islam", "hinduism", "judaism",
                  "church", "mosque", "temple", "bible", "quran", "religion",
                  "pope", "god"]),
    ("sports", ["football", "soccer", "basketball", "cricket", "tennis", "nba",
                "nfl", "fifa", "olympic", "ronaldo", "messi", "athlete"]),
    ("finance", ["stock", "market", "bitcoin", "crypto", "ethereum", "economy",
                 "inflation", "nasdaq", "investment", "currency"]),
    ("science", ["physics", "chemistry", "biology", "quantum", "astronomy",
                 "space", "nasa", "research", "genome", "climate"]),
    ("technology", ["software", "computer", "internet", "smartphone", "android",
                    "iphone", "tech", "programming", "startup", "semiconductor"]),
    ("entertainment", ["movie", "film", "music", "album", "song", "celebrity",
                       "actor", "singer", "swift", "netflix", "tv series",
                       "hollywood", "game of thrones"]),
    ("gaming", ["video game", "gaming", "esports", "playstation", "xbox",
                "nintendo", "minecraft", "fortnite"]),
    ("health", ["health", "disease", "covid", "vaccine", "medicine", "hospital",
                "mental health", "cancer", "virus"]),
    ("education", ["university", "school", "college", "education", "student",
                   "academic"]),
    ("commerce", ["shopping", "retail", "ecommerce", "store", "amazon", "sale"]),
    ("news", ["news", "breaking", "headline", "report"]),
]

# --- Subreddit -> category map (common large subreddits) -------------------
SUBREDDIT_CATEGORY: dict[str, str] = {
    "politics": "politics", "worldnews": "news", "news": "news",
    "conservative": "politics", "democrats": "politics",
    "movies": "entertainment", "television": "entertainment", "music": "entertainment",
    "popculturechat": "entertainment", "entertainment": "entertainment",
    "nba": "sports", "nfl": "sports", "soccer": "sports", "sports": "sports",
    "cricket": "sports",
    "christianity": "religion", "islam": "religion", "buddhism": "religion",
    "atheism": "religion", "religion": "religion",
    "technology": "technology", "programming": "technology", "gadgets": "technology",
    "artificial": "AI", "machinelearning": "AI", "openai": "AI", "chatgpt": "AI",
    "singularity": "AI", "localllama": "AI",
    "science": "science", "askscience": "science", "space": "science",
    "gaming": "gaming", "games": "gaming", "pcgaming": "gaming",
    "wallstreetbets": "finance", "stocks": "finance", "cryptocurrency": "finance",
    "personalfinance": "finance", "investing": "finance",
    "askreddit": "forums", "explainlikeimfive": "education", "todayilearned": "education",
    "health": "health", "medicine": "health", "fitness": "health",
    "nsfw": "pornography",
}


def _category_from_text(text: str) -> str:
    """Return the first matching category for a piece of text, else fallback."""
    low = text.lower()
    for category, keywords in KEYWORD_RULES:
        if any(kw in low for kw in keywords):
            return category
    return "miscellaneous"


def classify_domain_label(domain: str) -> tuple[str, str | None]:
    """Classify a single domain into ``(category, platform_label)``.

    Args:
        domain: A registrable domain or full host.

    Returns:
        A ``(category, platform_label_or_None)`` tuple.
    """
    d = (domain or "").lower()
    if d.startswith("www."):
        d = d[4:]
    platform = PLATFORM_LABELS.get(d)
    # Match against known registrable domains, allowing subdomain prefixes.
    for known, cat in DOMAIN_CATEGORY.items():
        if d == known or d.endswith("." + known):
            return cat, platform or PLATFORM_LABELS.get(known)
    # Fall back to keyword inference from the domain string itself.
    return _category_from_text(d), platform


def _upsert_classification(
    storage: Storage,
    source: str,
    entity_id: str,
    entity_label: str | None,
    entity_type: str | None,
    topic: str,
    category: str,
    method: str,
) -> None:
    """Insert or replace one ``entity_classification`` row."""
    storage.con.execute(
        "DELETE FROM entity_classification WHERE source = ? AND entity_id = ?",
        (source, entity_id),
    )
    storage.con.execute(
        """
        INSERT INTO entity_classification
            (source, entity_id, entity_label, entity_type, topic, category, method)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (source, entity_id, entity_label, entity_type, topic, category, method),
    )


def classify_domains(storage: Storage) -> int:
    """Label every domain in the ``domains`` table with category + platform.

    Args:
        storage: An open :class:`Storage`.

    Returns:
        Number of domains classified.
    """
    storage.upsert_domains_from_events()
    rows = storage.con.execute("SELECT domain_id, domain FROM domains").fetchall()
    count = 0
    for domain_id, domain in rows:
        category, platform = classify_domain_label(domain or "")
        storage.con.execute(
            """
            UPDATE domains
            SET category_label = ?, platform_label = ?, updated_at = now()
            WHERE domain_id = ?
            """,
            (category, platform, domain_id),
        )
        _upsert_classification(
            storage, "domain", domain, domain, "domain", category, category, "rule:domain"
        )
        count += 1
    logger.info("Classified %d domains", count)
    return count


def classify_wikipedia(storage: Storage) -> int:
    """Classify distinct Wikipedia article entities by title keywords.

    Args:
        storage: An open :class:`Storage`.

    Returns:
        Number of article entities classified.
    """
    rows = storage.con.execute(
        """
        SELECT DISTINCT entity_id, entity_label
        FROM attention_events
        WHERE source = 'wikimedia' AND entity_type = 'wikipedia_article'
        """
    ).fetchall()
    count = 0
    for entity_id, label in rows:
        category = _category_from_text(label or entity_id or "")
        topic = (label or entity_id or "unknown")
        _upsert_classification(
            storage, "wikimedia", entity_id, label, "wikipedia_article",
            topic, category, "rule:keyword",
        )
        count += 1
    logger.info("Classified %d Wikipedia articles", count)
    return count


def classify_reddit(storage: Storage) -> int:
    """Classify distinct subreddit entities by name lookup + keywords.

    Args:
        storage: An open :class:`Storage`.

    Returns:
        Number of subreddit entities classified.
    """
    rows = storage.con.execute(
        """
        SELECT DISTINCT entity_id, entity_label
        FROM attention_events
        WHERE source = 'reddit' AND entity_type = 'subreddit'
        """
    ).fetchall()
    count = 0
    for entity_id, label in rows:
        name = (label or "").lower()
        category = SUBREDDIT_CATEGORY.get(name) or _category_from_text(name)
        _upsert_classification(
            storage, "reddit", entity_id, label, "subreddit",
            label or entity_id, category, "rule:subreddit",
        )
        count += 1
    logger.info("Classified %d subreddits", count)
    return count


def available_categories() -> list[str]:
    """Return the default category taxonomy."""
    return list(DEFAULT_CATEGORIES)
