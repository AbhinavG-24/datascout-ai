# DataScout 🔎

Describe the data you need in plain English → get a clean, deduplicated, source-backed dataset.

## Features
- Natural-language prompts planned into workflows (AI mode via Claude, or heuristic mode with no key)
- robots.txt-aware, rate-limited, parallel crawling with optional link-following
- Extraction from JSON-LD, HTML tables, and LLM with evidence checks
- Validation, fuzzy deduplication, confidence scores
- New / changed / removed tracking across re-runs, plus scheduled re-runs
- Dashboard: search, filters, sources, analytics, logs, record inspector
- Export to CSV, JSON, NDJSON

## Quick start
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...   # optional
    uvicorn server:app --port 8000        # http://localhost:8000

## Structure
db.py · engine.py · server.py · static/ (index.html, style.css, app.js)

## Limitations
Static HTML only (no JavaScript rendering), single user, SQLite.

## Responsible use
Respect each site's terms and robots.txt, and applicable data-protection laws.