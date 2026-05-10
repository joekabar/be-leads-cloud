# be-leads

## What this is

be-leads is a high-volume, recurring scraper that builds a Belgian B2B company database from
multiple authoritative and discovery sources: KBO Open Data (canonical bulk), kbopub HTML
(function holders), NBB CBSO Authentic Data (financials), goudengids/pagesdor (discovery),
company websites (enrichment), and DuckDuckGo + Brave (cross-validation). All scraped facts are
stored with full provenance in a single Postgres database; a Streamlit UI serves sector × city
queries.

## Quick start

```bash
uv python install 3.12 && uv sync --locked --dev && uv run playwright install chromium
docker compose up -d pg
uv run pytest -m "not network"
uv run streamlit run src/scraper/ui/app.py
```

## Repo layout

See [CLAUDE.md](CLAUDE.md) for the full operating manual (conventions, hooks, definition of done)
and [agent_docs/architecture.md](agent_docs/architecture.md) for the architecture overview.
