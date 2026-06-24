# Civilizational Attention Ledger

A **local-first research pipeline** that approximates a *time-use survey for the
web* using free / public datasets. It produces operational datasets,
exportable research tables, and a dashboard showing how collective attention is
distributed across **websites, domains, subdomains, platforms, topics, and
time**.

The project prioritizes **speed, extensibility, and interpretability** over
perfect measurement. "Attention" is treated as a *plural* construct measured
through proxies: pageviews, posts/comments, news-URL circulation, domain ranks,
and web-graph prominence.

> Core research question: **How is public web attention distributed across
> domains, platforms, communities, topics, and temporal rhythms?**

---

## What this measures

The system models five distinct **attention signals**, never collapsing them
into one number without preserving the source-level scores:

| Signal | Meaning | Example source | Metric |
| --- | --- | --- | --- |
| `pageview_attention`  | visits / views                | Wikimedia      | article views |
| `discursive_attention`| posts / comments              | Reddit         | posts, comments, link shares |
| `news_attention`      | article publication/circulation | GDELT        | article counts |
| `rank_attention`      | relative popularity rank      | Tranco / Cloudflare | inverse rank |
| `structural_attention`| link / inlink centrality      | Common Crawl   | inverse harmonic-centrality rank |

Every table preserves `source` and `attention_signal` so heterogeneous
measurements stay inspectable.

## What this does **not** measure

See **Caveats** below — this is the most important section. In short: it is not
literal time spent, it overrepresents public/textual/measurable activity, and
it largely misses platform-internal behavior (YouTube, TikTok, Instagram,
Facebook, Discord).

---

## Quickstart

```bash
# 1. Install (editable) with dashboard extras
python -m pip install -e ".[dashboard]"

# 2. Run the full offline demo (Wikimedia + GDELT + Tranco, synthetic data)
make demo

# 3. Explore in the dashboard
attention-ledger dashboard
#   or: streamlit run src/attention_ledger/dashboards/app.py

# 4. (Re)export research CSVs
attention-ledger export --format csv --out data/exports/
```

`make demo` runs in **offline mode** (`ATTENTION_LEDGER_OFFLINE=true`) so it
works with no outbound network access, generating deterministic synthetic data.
To hit live public APIs instead:

```bash
ATTENTION_LEDGER_OFFLINE=false make demo
```

### Demo outputs

```
data/processed/attention_ledger.duckdb     # populated database
data/exports/domain_daily.csv
data/exports/topic_daily.csv
data/exports/attention_index_daily.csv
data/exports/top_domains_by_source.csv
data/exports/top_topics_by_source.csv
data/exports/attention_spikes.csv
```

---

## How to run it (commands)

```bash
attention-ledger init                       # create DuckDB + schema

# Ingest (each stores raw payloads + logs the run)
attention-ledger ingest wikimedia --start 2026-01-01 --end 2026-01-07 --project en.wikipedia
attention-ledger ingest gdelt --start 2026-01-01 --end 2026-01-07 --query "AI OR artificial intelligence"
attention-ledger ingest tranco --input tranco.csv            # or --demo to synthesize
attention-ledger ingest cloudflare --input radar.csv
attention-ledger ingest reddit --input dump.jsonl.zst        # .jsonl/.jsonl.zst/.csv/.parquet
attention-ledger ingest commoncrawl --input domain-ranks.txt.gz --limit 100000

# Classify (rule-based first pass)
attention-ledger classify domains
attention-ledger classify wikipedia
attention-ledger classify reddit

# Build aggregates + composite index
attention-ledger build daily

# Export research tables
attention-ledger export --format csv --out data/exports/

# Dashboard
attention-ledger dashboard
```

---

## Where each dataset comes from

| Source | Provider | Access | Notes |
| --- | --- | --- | --- |
| **Wikimedia Pageviews** | Wikimedia REST API (`/metrics/pageviews/top`) | Free, no key | High-resolution public attention traces. |
| **GDELT** | GDELT DOC 2.0 API | Free, no key | News/media attention; article URLs + domains. |
| **Tranco** | [tranco-list.eu](https://tranco-list.eu) | Free CSV download | Research-grade domain popularity list. |
| **Cloudflare Radar** | Cloudflare Radar | CSV export (API needs token) | Domain popularity + category labels. |
| **Reddit dumps** | Pushshift-style archives | Download | Community-level discursive activity. |
| **Common Crawl web graph** | Common Crawl `domain-ranks` files | Download | Supply-side structural centrality (lowest priority). |

The first four are the lowest-friction sources and power the demo. Reddit and
Common Crawl are larger / less directly attention-related and are built last.

---

## Data model (DuckDB)

Database: `data/processed/attention_ledger.duckdb`

- **`attention_events`** — atomic normalized observations (one per
  source/signal/entity/metric/timestamp). Carries `raw_payload_path` provenance.
- **`domains`** — registrable domain / subdomain / tld decomposition plus
  `platform_label` and `category_label`.
- **`entity_classification`** — entity → `topic` / `category` mapping.
- **`domain_daily`** — daily per-domain aggregates with within-(source,date)
  `normalized_value` percentile and `rank_within_source`.
- **`topic_daily`** — daily per-topic aggregates with `top_entities` /
  `top_domains`.
- **`attention_index_daily`** — composite index (per-signal scores + mean
  composite + `source_coverage_count`).
- **`ingestion_runs`** — audit log of every ingestion run.

---

## Composite attention index

A deliberately conservative first pass. For each source and date:

1. aggregate the metric by domain/topic;
2. log-transform values (`log1p`);
3. convert to a **percentile rank within (source, date)** → a 0–1 score;
4. store that as the source/signal-specific score column;
5. **composite = mean of the *available* signal scores**;
6. record `source_coverage_count` (how many signals contributed).

```
composite_attention_score =
    mean(pageview_score, discursive_score, news_score, rank_score, structural_score)
    # over the signals that are present
```

**Never** compare raw pageviews directly to raw Reddit comments or news article
counts — the percentile-within-source step exists precisely to avoid that, and
each signal keeps its own column so you can always disaggregate.

---

## How to add a new data source

The connector interface is intentionally small, leaving a clean seam for paid
or semi-private sources (Similarweb, Comscore, browser-history exports, YouTube
API, …):

1. Create `src/attention_ledger/sources/<name>.py` with an `ingest(...)`
   function returning a `list[AttentionEvent]`.
2. Pick the right `AttentionSignal` (or add one in `schemas.py`) and set
   `source`, `entity_type`, `metric_name`, `metric_value`.
3. Store raw payloads via `sources._common.store_raw(...)` before transforming.
4. Register a CLI subcommand in `cli.py` (it will reuse `_persist`, which writes
   events, refreshes `domains`, and logs the run).
5. (Optional) add a `classify_<name>` rule set in `transforms/classify_topics.py`.
6. Add a unit test in `tests/` covering a couple of sample rows.

Each connector is independently testable and never silently swallows errors.

---

## How to interpret the composite index

- Read scores **comparatively**, not absolutely. A composite of 0.8 means
  "high relative to other entities in this source/date," not "80% of attention."
- A high `source_coverage_count` means an entity is salient across *different
  kinds* of attention (e.g. published-about **and** popular **and** discussed).
- The most interesting findings are often *mismatches*: high news but low
  pageview ("what institutions publish vs. what people look up"), or high rank
  but low structural centrality ("culturally central but structurally
  peripheral"). The dashboard and the per-signal columns are built for exactly
  these comparisons.

Research prompts the outputs are designed to support:

- "What was the internet paying attention to this week?"
- "Which domains mediate political consciousness?"
- "What topics dominate news but not Wikipedia?"
- "What is culturally central but structurally peripheral?"
- "Where does entertainment dwarf politics?"

---

## ⚠️ Caveats (read this)

- **This is not literal time spent.**
- Free datasets **overrepresent** public, textual, and measurable activity.
- **Passive consumption is undercounted.**
- **Platform-internal behavior is mostly missing.**
- **YouTube, TikTok, Instagram, Facebook, and Discord are poorly captured.**
- **Composite scores are heuristic.**
- Different signals **should not be collapsed** without preserving source-level
  scores.
- Rankings are better interpreted **comparatively than absolutely**.

---

## Project layout

```
attention-ledger/
  README.md  pyproject.toml  Makefile  .env.example
  data/{raw,interim,processed,exports}/
  src/attention_ledger/
    cli.py  config.py  schemas.py  storage.py  exports.py
    sources/{wikimedia,reddit,gdelt,tranco,cloudflare,commoncrawl}.py
    transforms/{normalize_domains,classify_topics,aggregate_attention,score_attention}.py
    dashboards/app.py
    utils/{dates,urls,logging}.py
  tests/
```

## Development

```bash
python -m pip install -e ".[dev,dashboard]"
make test     # pytest
make lint     # ruff
```

## Tech stack

Python 3.11+ · DuckDB · Polars/Pandas · Typer · Pydantic · httpx · Parquet ·
Streamlit. Optional scikit-learn / sentence-transformers for ML classification
later.

## License

MIT.
