"""Streamlit dashboard for the Civilizational Attention Ledger.

Run with:

    streamlit run src/attention_ledger/dashboards/app.py
    # or
    attention-ledger dashboard

The dashboard reads directly from the DuckDB database and offers filters for
date range, source, attention signal, domain, category, and topic. It surfaces:
top domains/topics by proxy, time series, a platform comparison, a source
coverage matrix, attention spikes, and the composite "attention ledger" table.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

# Make the package importable when launched via `streamlit run path/to/app.py`.
_PKG_ROOT = Path(__file__).resolve().parents[2]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from attention_ledger.config import get_config  # noqa: E402

CAVEATS = """
**What this is and is not.** This dashboard measures *proxies* for attention,
not literal time spent. Free datasets overrepresent public, textual, and
measurable activity; passive consumption is undercounted; platform-internal
behavior on YouTube, TikTok, Instagram, Facebook, and Discord is largely
missing. Composite scores are heuristic — different signals should not be
collapsed without preserving source-level scores. Rankings are best read
*comparatively*, not absolutely.
"""


@st.cache_resource
def _connect(db_path: str) -> duckdb.DuckDBPyConnection:
    """Open a read-only DuckDB connection (cached across reruns)."""
    return duckdb.connect(db_path, read_only=True)


def _q(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> pd.DataFrame:
    """Run a query and return a DataFrame (empty on missing tables)."""
    try:
        return con.execute(sql, params or []).fetchdf()
    except duckdb.Error as exc:  # pragma: no cover - defensive UI guard
        st.warning(f"Query failed: {exc}")
        return pd.DataFrame()


def _distinct(con, table: str, col: str) -> list:
    df = _q(con, f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL ORDER BY {col}")
    return df[col].tolist() if not df.empty else []


def main() -> None:
    st.set_page_config(page_title="Civilizational Attention Ledger", layout="wide")
    st.title("🌐 Civilizational Attention Ledger")
    st.caption(
        "An approximate time-use survey for the web, assembled from free public "
        "datasets. Attention is modeled as a plural construct."
    )

    cfg = get_config()
    db_path = str(cfg.db_path)
    if not Path(db_path).exists():
        st.error(
            f"Database not found at {db_path}. Run `make demo` or "
            "`attention-ledger init` followed by ingestion + `build daily`."
        )
        st.info(CAVEATS)
        return

    con = _connect(db_path)

    if con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name='attention_events'"
    ).fetchone()[0] == 0 or _q(con, "SELECT count(*) AS n FROM attention_events")["n"].iloc[0] == 0:
        st.warning("No attention events ingested yet. Run an ingest command, then `build daily`.")
        st.info(CAVEATS)
        return

    # --- Sidebar filters --------------------------------------------------
    st.sidebar.header("Filters")
    drange = _q(con, "SELECT min(date) AS lo, max(date) AS hi FROM domain_daily")
    if drange.empty or pd.isna(drange["lo"].iloc[0]):
        st.warning("No daily aggregates yet. Run `attention-ledger build daily`.")
        st.info(CAVEATS)
        return
    lo, hi = drange["lo"].iloc[0], drange["hi"].iloc[0]
    date_sel = st.sidebar.date_input("Date range", value=(lo, hi), min_value=lo, max_value=hi)
    if isinstance(date_sel, tuple) and len(date_sel) == 2:
        start_d, end_d = date_sel
    else:
        start_d, end_d = lo, hi

    sources = _distinct(con, "domain_daily", "source")
    signals = _distinct(con, "domain_daily", "attention_signal")
    categories = _distinct(con, "domains", "category_label")
    topics = _distinct(con, "topic_daily", "topic")

    sel_sources = st.sidebar.multiselect("Source", sources, default=sources)
    sel_signals = st.sidebar.multiselect("Attention signal", signals, default=signals)
    sel_categories = st.sidebar.multiselect("Category (domain)", categories, default=[])
    sel_topics = st.sidebar.multiselect("Topic", topics, default=[])
    domain_search = st.sidebar.text_input("Domain contains", "")

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Caveats**")
    st.sidebar.caption(CAVEATS)

    src_filter = "AND source IN (" + ",".join(["?"] * len(sel_sources)) + ")" if sel_sources else ""
    sig_filter = (
        "AND attention_signal IN (" + ",".join(["?"] * len(sel_signals)) + ")"
        if sel_signals
        else ""
    )
    base_params: list = [start_d, end_d]
    extra_params = list(sel_sources) + list(sel_signals)

    # --- 1. Top domains ---------------------------------------------------
    st.header("1. Top domains by attention proxy")
    cat_clause = (
        "AND domain IN (SELECT domain FROM domains WHERE category_label IN ("
        + ",".join(["?"] * len(sel_categories))
        + "))"
        if sel_categories
        else ""
    )
    dom_sql = f"""
        SELECT domain, source, attention_signal,
               sum(metric_value) AS total_metric,
               avg(normalized_value) AS avg_normalized
        FROM domain_daily
        WHERE date BETWEEN ? AND ? {src_filter} {sig_filter} {cat_clause}
        {"AND lower(domain) LIKE ?" if domain_search else ""}
        GROUP BY domain, source, attention_signal
        ORDER BY avg_normalized DESC
        LIMIT 30
    """
    dom_params = (
        base_params
        + extra_params
        + (list(sel_categories) if sel_categories else [])
        + ([f"%{domain_search.lower()}%"] if domain_search else [])
    )
    top_domains = _q(con, dom_sql, dom_params)
    st.dataframe(top_domains, use_container_width=True)
    if not top_domains.empty:
        chart = top_domains.groupby("domain")["avg_normalized"].max().sort_values(ascending=False).head(15)
        st.bar_chart(chart)

    # --- 2. Top topics ----------------------------------------------------
    st.header("2. Top topics by attention proxy")
    topic_sql = f"""
        SELECT topic, source, attention_signal,
               sum(metric_value) AS total_metric,
               avg(normalized_value) AS avg_normalized
        FROM topic_daily
        WHERE date BETWEEN ? AND ? {src_filter} {sig_filter}
        {"AND topic IN (" + ",".join(["?"] * len(sel_topics)) + ")" if sel_topics else ""}
        GROUP BY topic, source, attention_signal
        ORDER BY total_metric DESC
        LIMIT 30
    """
    topic_params = base_params + extra_params + (list(sel_topics) if sel_topics else [])
    top_topics = _q(con, topic_sql, topic_params)
    st.dataframe(top_topics, use_container_width=True)
    if not top_topics.empty:
        tchart = top_topics.groupby("topic")["total_metric"].sum().sort_values(ascending=False).head(15)
        st.bar_chart(tchart)

    # --- 3. Time series ---------------------------------------------------
    st.header("3. Time series")
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("By domain (normalized)")
        ts_dom = _q(
            con,
            f"""
            SELECT date, domain, avg(normalized_value) AS norm
            FROM domain_daily
            WHERE date BETWEEN ? AND ? {src_filter} {sig_filter}
            GROUP BY date, domain
            """,
            base_params + extra_params,
        )
        if not ts_dom.empty:
            leaders = ts_dom.groupby("domain")["norm"].mean().sort_values(ascending=False).head(8).index
            pivot = ts_dom[ts_dom["domain"].isin(leaders)].pivot_table(
                index="date", columns="domain", values="norm"
            )
            st.line_chart(pivot)
    with col_b:
        st.subheader("By topic (metric)")
        ts_top = _q(
            con,
            f"""
            SELECT date, topic, sum(metric_value) AS metric
            FROM topic_daily
            WHERE date BETWEEN ? AND ? {src_filter} {sig_filter}
            GROUP BY date, topic
            """,
            base_params + extra_params,
        )
        if not ts_top.empty:
            leaders = ts_top.groupby("topic")["metric"].sum().sort_values(ascending=False).head(8).index
            pivot = ts_top[ts_top["topic"].isin(leaders)].pivot_table(
                index="date", columns="topic", values="metric"
            )
            st.line_chart(pivot)

    # --- 4. Platform comparison ------------------------------------------
    st.header("4. Platform comparison")
    plat = _q(
        con,
        """
        SELECT d.platform_label,
               sum(dd.metric_value) AS total_metric,
               count(DISTINCT dd.domain) AS domains
        FROM domain_daily dd
        JOIN domains d ON d.domain = dd.domain
        WHERE d.platform_label IS NOT NULL AND dd.date BETWEEN ? AND ?
        GROUP BY d.platform_label
        ORDER BY total_metric DESC
        """,
        [start_d, end_d],
    )
    if plat.empty:
        st.caption("No platform-labeled domains in range (run `classify domains`).")
    else:
        st.bar_chart(plat.set_index("platform_label")["total_metric"])

    # --- 5. Source coverage matrix ---------------------------------------
    st.header("5. Source coverage matrix")
    cov = _q(
        con,
        """
        SELECT source, attention_signal,
               count(*) AS rows,
               count(DISTINCT date) AS days,
               count(DISTINCT domain) AS domains
        FROM domain_daily
        GROUP BY source, attention_signal
        ORDER BY source
        """,
    )
    st.dataframe(cov, use_container_width=True)

    # --- 6. Attention spikes ---------------------------------------------
    st.header("6. Attention spikes")
    spikes = _q(
        con,
        f"""
        WITH series AS (
            SELECT date, domain, source, attention_signal, metric_value, normalized_value,
                   lag(normalized_value) OVER (
                       PARTITION BY domain, source, attention_signal ORDER BY date
                   ) AS prev_norm
            FROM domain_daily
            WHERE date BETWEEN ? AND ? {src_filter} {sig_filter}
        )
        SELECT date, domain, source, attention_signal, metric_value,
               normalized_value, (normalized_value - prev_norm) AS norm_delta
        FROM series
        WHERE prev_norm IS NOT NULL AND (normalized_value - prev_norm) >= 0.2
        ORDER BY norm_delta DESC
        LIMIT 50
        """,
        base_params + extra_params,
    )
    if spikes.empty:
        st.caption("No spikes detected in the selected range (need >= 2 days of data).")
    else:
        st.dataframe(spikes, use_container_width=True)

    # --- 7. Composite ledger summary -------------------------------------
    st.header("7. Civilizational attention ledger (composite)")
    st.caption(
        "Composite = mean of available signal percentile scores. "
        "source_coverage_count shows how many signals contributed."
    )
    level = st.radio("Level", ["domain", "topic"], horizontal=True)
    ledger = _q(
        con,
        """
        SELECT domain_or_topic, level,
               avg(pageview_score)   AS pageview,
               avg(discursive_score) AS discursive,
               avg(news_score)       AS news,
               avg(rank_score)       AS rank,
               avg(structural_score) AS structural,
               avg(composite_attention_score) AS composite,
               max(source_coverage_count) AS coverage
        FROM attention_index_daily
        WHERE level = ? AND date BETWEEN ? AND ?
        GROUP BY domain_or_topic, level
        ORDER BY composite DESC
        LIMIT 50
        """,
        [level, start_d, end_d],
    )
    st.dataframe(ledger, use_container_width=True)


if __name__ == "__main__":
    main()
