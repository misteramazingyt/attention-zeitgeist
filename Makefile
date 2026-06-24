.PHONY: help install dev-install demo live-demo preflight init test lint dashboard clean export

PY ?= python3
CLI = $(PY) -m attention_ledger.cli
DEMO_START ?= 2026-01-01
DEMO_END ?= 2026-01-07
# Live-run window (recent days; Wikimedia pageviews lag ~1-2 days).
LIVE_START ?= 2026-06-20
LIVE_END ?= 2026-06-22
LIVE_QUERY ?= AI OR artificial intelligence

help:
	@echo "Attention Ledger - make targets"
	@echo "  make install       Install the package and core dependencies"
	@echo "  make dev-install   Install with dev + dashboard extras"
	@echo "  make demo          Run the end-to-end demo pipeline (offline-friendly)"
	@echo "  make init          Initialize the DuckDB database and schema"
	@echo "  make test          Run the unit test suite"
	@echo "  make lint          Run ruff lint checks"
	@echo "  make dashboard     Launch the Streamlit dashboard"
	@echo "  make export        Export research CSV tables"
	@echo "  make clean         Remove generated data artifacts"

install:
	$(PY) -m pip install -e .

dev-install:
	$(PY) -m pip install -e ".[dev,dashboard]"

init:
	$(CLI) init

# End-to-end demo using the lowest-friction sources: Wikimedia, GDELT, Tranco.
# Runs in offline mode so it works without outbound network access; set
# ATTENTION_LEDGER_OFFLINE=false to hit live APIs instead.
demo:
	ATTENTION_LEDGER_OFFLINE=$${ATTENTION_LEDGER_OFFLINE:-true} $(CLI) init
	ATTENTION_LEDGER_OFFLINE=$${ATTENTION_LEDGER_OFFLINE:-true} $(CLI) ingest wikimedia --start $(DEMO_START) --end $(DEMO_END) --project en.wikipedia
	ATTENTION_LEDGER_OFFLINE=$${ATTENTION_LEDGER_OFFLINE:-true} $(CLI) ingest gdelt --start $(DEMO_START) --end $(DEMO_END) --query "AI OR artificial intelligence"
	ATTENTION_LEDGER_OFFLINE=$${ATTENTION_LEDGER_OFFLINE:-true} $(CLI) ingest tranco --input data/raw/tranco_demo.csv --demo --as-of $(DEMO_START)
	$(CLI) classify domains
	$(CLI) classify wikipedia
	$(CLI) build daily
	$(CLI) export --format csv --out data/exports/
	@echo ""
	@echo "Demo complete. Artifacts:"
	@echo "  data/processed/attention_ledger.duckdb"
	@echo "  data/exports/*.csv"

# Preflight: confirm the data APIs are reachable through the egress policy
# before attempting a live run. Reports the blocked host instead of failing
# deep inside an ingest command.
preflight:
	@echo "Checking egress to Wikimedia and GDELT..."
	@for h in https://wikimedia.org/api/rest_v1 https://api.gdeltproject.org; do \
		code=$$(curl -s -o /dev/null -w "%{http_code}" "$$h" --max-time 20 2>/dev/null); \
		if [ "$$code" = "000" ] || [ "$$code" = "403" ] || [ "$$code" = "407" ]; then \
			echo "  BLOCKED: $$h (HTTP $$code) - allow this host in the environment network policy"; \
		else \
			echo "  OK: $$h (HTTP $$code)"; \
		fi; \
	done

# Live dry run against the real Wikimedia + GDELT APIs (no synthetic data).
# Requires the network policy to allow wikimedia.org and api.gdeltproject.org.
live-demo: preflight
	ATTENTION_LEDGER_OFFLINE=false $(CLI) init
	ATTENTION_LEDGER_OFFLINE=false $(CLI) ingest wikimedia --start $(LIVE_START) --end $(LIVE_END) --project en.wikipedia
	ATTENTION_LEDGER_OFFLINE=false $(CLI) ingest gdelt --start $(LIVE_START) --end $(LIVE_END) --query "$(LIVE_QUERY)"
	$(CLI) classify domains
	$(CLI) classify wikipedia
	$(CLI) build daily
	$(CLI) export --format csv --out data/exports/
	@echo ""
	@echo "Live run complete. Artifacts in data/processed/ and data/exports/"

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src tests

dashboard:
	streamlit run src/attention_ledger/dashboards/app.py

export:
	$(CLI) export --format csv --out data/exports/

clean:
	rm -f data/processed/*.duckdb data/processed/*.duckdb.wal
	rm -f data/exports/*.csv
	rm -rf data/raw/* data/interim/*
	@find data -type d -empty -exec touch {}/.gitkeep \;
