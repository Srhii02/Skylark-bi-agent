# Decision Log

## Key assumptions
1. **Column titles, not monday's internal column ids, are the stable key.**
   monday.com assigns opaque ids (e.g. `text_mkr2x1a9`) at import time that
   differ per import. The client fetches board schema first and keys every
   row by column *title* (matching the original CSV headers) so the pipeline
   isn't tied to one specific import.
2. **Deals and Work Orders do not share a reliable join key.** Deals use
   `Client Code` (`COMPANY089`); Work Orders use `Customer Name Code`
   (`WOCOMPANY_002`) — different numbering schemes, no overlap found. Both
   *do* share `Owner code` / `BD/KAM Personnel code` (`OWNER_00N`) and
   `Sector`. **Decision:** never attempt a row-level match between a specific
   deal and a specific work order — deal names are masked/randomized
   (Naruto, Sasuke...) and reused across unrelated deals, so fuzzy-matching
   on them would produce confidently wrong answers. Cross-board questions
   are answered by aggregating each board independently on shared dimensions
   (owner, sector, time) instead. The agent says this explicitly when a
   question implies a record-level match.
3. **A row is treated as corrupted (not a real record) if a field's value
   literally equals its own column's title** — found once in the sample
   Deals data (a "deal" whose `Deal Status` = `"Deal Status"`). Dropped, and
   the drop is counted and reported, not silently discarded.
4. **Missing values are never coerced to zero.** A blank `Deal Value` means
   "unknown," not "$0" — silently zeroing missing deal values would
   understate pipeline totals. The cleaning layer counts and reports missing
   rates per field so the agent can caveat answers appropriately.
5. **Quantity fields carry inconsistent, sometimes-absent units** in the
   *same column* ("5360 HA", "4", "45days", "2 location", "NA",
   "1,310.850"). The numeric portion and unit are parsed separately rather
   than forcing one unit system — that would need domain knowledge not
   present in the data. The agent is instructed to state units rather than
   summing heterogeneous quantities.

## Trade-offs and why
- **Two broad data tools (`get_deals`, `get_work_orders`, lightly filterable)
  instead of many narrow, pre-aggregated ones.** Keeps the tool surface
  small and lets Claude reason over raw-but-clean records in-context, which
  is more flexible for open-ended founder questions a fixed metrics API
  couldn't anticipate. Trade-off: at much larger board sizes this would need
  server-side aggregation instead of shipping full record sets to the
  model — fine at this data's scale (~100s of rows/board).
- **Streamlit over a custom React/FastAPI split** — fastest path to a
  cleanly "hosted, testable without local setup" prototype (free on
  Streamlit Community Cloud) within a 6-hour budget. A production version
  would split a proper API from a richer frontend.
- **In-process 3-minute cache, not a database.** Satisfies "must query
  monday.com dynamically, don't hardcode CSV data" while avoiding hammering
  the API on every chat turn. No persistence — fine for a single-user
  prototype, not for concurrent multi-user production use.
- **Read-only integration**, matching the stated requirement directly; no
  write-back to monday.com attempted.
- **Retry-with-backoff + surfaced errors, not silent failure**, for API
  calls: transient monday.com errors (5xx, rate limits) are retried up to 3
  times; persistent failures are returned to the agent as a tool error so it
  can tell the user what happened, rather than crashing the chat.

## "Leadership updates" — my interpretation
The agent produces a short, copy-pasteable executive summary on request
(e.g. "give me a leadership update on pipeline") — bullet points, key
metrics, notable movement, flagged risks/data gaps — instead of a raw data
dump. This is handled via the system prompt's output-format instruction, not
a separate feature, since the underlying data-fetching is identical to any
other query; only the output shape changes. I did not build a
scheduled/automated report (e.g. weekly email digest) — out of scope for a
conversational prototype in this time budget.

## What I'd do differently with more time
- A lightweight, *probabilistic* entity-resolution pass linking Deals ↔ Work
  Orders via owner + sector + approximate value/date windows, with
  confidence shown to the user — rather than no linkage at all.
- Pre-aggregated summary metrics (open pipeline by sector/stage, billed vs.
  collected by month), refreshed on a schedule, so large boards don't need
  to ship full record sets to the model every turn.
- Streaming responses, inline links back to specific monday.com item rows.
- Automated tests on `data_cleaning.py` using the real messy sample rows
  (the header-corruption row, the `#VALUE!` cell, mixed-unit quantities) as
  fixtures.
- Basic auth on the hosted prototype instead of an unauthenticated public
  link.

## Tech stack
Python, Streamlit, monday.com GraphQL API (`requests`), Anthropic Claude
(tool use), `python-dateutil`. Chosen for fast, explainable iteration within
the time budget and free, no-setup hosting.
