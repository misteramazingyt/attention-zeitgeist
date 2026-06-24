# Notebooks

Exploratory analysis notebooks live here. They read directly from the DuckDB
database produced by the pipeline.

```python
import duckdb
con = duckdb.connect("../data/processed/attention_ledger.duckdb", read_only=True)

# What topics dominate news but not Wikipedia?
con.execute("""
    WITH news AS (
        SELECT topic, sum(metric_value) m FROM topic_daily
        WHERE source='gdelt' GROUP BY topic
    ),
    wiki AS (
        SELECT topic, sum(metric_value) m FROM topic_daily
        WHERE source='wikimedia' GROUP BY topic
    )
    SELECT n.topic, n.m AS news, coalesce(w.m,0) AS wiki
    FROM news n LEFT JOIN wiki w USING (topic)
    ORDER BY news DESC
""").fetchdf()
```

See the project README for the full data model and interpretation guidance.
