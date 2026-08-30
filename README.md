# Skylark Drones — monday.com Business Intelligence Agent

A conversational agent that answers founder-level business questions by
querying live monday.com data (Deals + Work Orders boards), cleaning it on
the fly, and reasoning over it with Claude.

## Architecture

```
User (chat) → Streamlit UI (app.py)
                 │
                 ▼
        Claude agent loop (backend/agent.py)
                 │  tool calls
                 ▼
   backend/tools.py  →  backend/monday_client.py  →  monday.com GraphQL API
                 │
                 ▼
   backend/data_cleaning.py (normalize, flag data quality issues)
```

- **`backend/monday_client.py`** — GraphQL client. Fetches items via
  cursor-paginated `items_page`, and maps monday's opaque column ids to their
  human-readable titles so the rest of the code isn't tied to one specific
  import.
- **`backend/data_cleaning.py`** — Normalizes raw board rows: parses numbers
  with embedded units ("5360 HA" → 5360, unit "HA"), parses inconsistent
  dates defensively, drops corrupted rows (e.g. a re-entered header row found
  in the sample Deals data), and — critically — never silently fills missing
  values. It produces a `CleaningReport` (missing-value counts per field,
  dropped rows, parse errors) that gets attached to every tool result.
- **`backend/tools.py`** — Two data tools (`get_deals`, `get_work_orders`,
  each filterable by sector/status/stage) plus `get_join_limitations`, exposed
  to Claude as tool schemas. Board data is cached in-process for 3 minutes to
  respect monday's rate limits, then re-fetched — nothing from the original
  CSVs is hardcoded.
- **`backend/agent.py`** — The tool-use loop. System prompt instructs Claude
  to always fetch before answering, surface data-quality caveats when they
  matter, ask one clarifying question on genuine ambiguity, and otherwise
  state its assumption and proceed.
- **`app.py`** — Streamlit chat UI; the whole thing is one deployable app.

## Setup

### 1. Import the data into monday.com
1. Create two boards from the provided files: **Deals** and **Work Orders**.
2. Use monday's CSV/XLSX import (Board → ⋯ → Import data). Let monday infer
   column types; the agent reads by column *title*, so keep the original
   headers from the source files (e.g. "Deal Stage", "Sector/service",
   "BD/KAM Personnel code", "Amount in Rupees (Incl of GST) (Masked)", etc.)
   — if you rename a column, update the matching key in `data_cleaning.py`.
3. Grab each board's numeric ID from its URL:
   `https://<yourteam>.monday.com/boards/1234567890`.

### 2. Get API credentials
- **monday.com**: Admin avatar → Admin → API → generate a personal token
  (read access is sufficient — this agent never writes).
- **Anthropic**: an API key from console.anthropic.com.

### 3. Configure
Copy `.env.example` to `.env` for local runs, **or**, for Streamlit Cloud,
add the same four values under Settings → Secrets:
```toml
MONDAY_API_TOKEN = "..."
MONDAY_DEALS_BOARD_ID = "..."
MONDAY_WORK_ORDERS_BOARD_ID = "..."
ANTHROPIC_API_KEY = "..."
```

### 4. Run
```bash
pip install -r requirements.txt
streamlit run app.py
```

### 5. Deploy (for the hosted-link deliverable)
Push this repo to GitHub, then deploy for free on
[Streamlit Community Cloud](https://streamlit.io/cloud): New app → point at
`app.py` → paste the four secrets above → Deploy. No local setup required to
test it afterward.

## Known limitations (see DECISION_LOG.md for the full reasoning)
- Deals and Work Orders don't share a reliable per-record join key in the
  sample data (`Client Code` vs `Customer Name Code` are different ID
  spaces). Cross-board answers work at the aggregate level (sector, owner
  code, time period), not row-by-row deal↔work-order matching.
- The agent is read-only by design, per the assignment's integration
  requirements.
