"""
Tools exposed to the Claude agent. Each tool fetches live from monday.com
(via monday_client) and returns cleaned, compact JSON — never the raw board.

Board data is cached per Streamlit session for a few minutes so a single
conversation doesn't re-fetch on every turn (monday.com has API rate limits),
while still being "dynamic" per the assignment's requirement — nothing is
hardcoded from the original CSVs.
"""

from __future__ import annotations
import time
from typing import Any

from . import monday_client
from . import data_cleaning as dc

_CACHE: dict[str, Any] = {}
_CACHE_TTL_SECONDS = 180


def _cached_board(board_id: str, api_token: str, cleaner) -> tuple[list[dict], dc.CleaningReport]:
    key = board_id
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit["ts"] < _CACHE_TTL_SECONDS:
        return hit["rows"], hit["report"]

    raw = monday_client.get_board_items(board_id, api_token)
    rows, report = cleaner(raw)
    _CACHE[key] = {"ts": now, "rows": rows, "report": report}
    return rows, report


def get_deals(deals_board_id: str, api_token: str, sector: str | None = None,
              status: str | None = None, stage: str | None = None) -> dict:
    rows, report = _cached_board(deals_board_id, api_token, dc.clean_deals)
    filtered = rows
    if sector:
        filtered = [r for r in filtered if (r["sector"] or "").lower() == sector.lower()]
    if status:
        filtered = [r for r in filtered if (r["status"] or "").lower() == status.lower()]
    if stage:
        filtered = [r for r in filtered if stage.lower() in (r["deal_stage"] or "").lower()]
    return {
        "records": filtered,
        "record_count": len(filtered),
        "total_records_on_board": report.total_rows,
        "data_quality_notes": report.summary(),
    }


def get_work_orders(work_orders_board_id: str, api_token: str, sector: str | None = None,
                     execution_status: str | None = None) -> dict:
    rows, report = _cached_board(work_orders_board_id, api_token, dc.clean_work_orders)
    filtered = rows
    if sector:
        filtered = [r for r in filtered if (r["sector"] or "").lower() == sector.lower()]
    if execution_status:
        filtered = [r for r in filtered if (r["execution_status"] or "").lower() == execution_status.lower()]
    return {
        "records": filtered,
        "record_count": len(filtered),
        "total_records_on_board": report.total_rows,
        "data_quality_notes": report.summary(),
    }


def get_join_limitations(*_args, **_kwargs) -> dict:
    return {"note": dc.NOTE_ON_JOINING}


TOOL_SCHEMAS = [
    {
        "name": "get_deals",
        "description": (
            "Fetch sales pipeline / deals data live from the monday.com Deals board. "
            "Optionally filter by sector, deal status (Open/On Hold/Dead), or deal "
            "stage (e.g. 'Negotiations', 'Proposal'). Always returns data_quality_notes "
            "describing missing/dropped data — read and mention relevant caveats."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {"type": "string", "description": "e.g. Mining, Renewables, Railways, Powerline, DSP, Construction, Tender, Others"},
                "status": {"type": "string", "description": "Open, On Hold, or Dead"},
                "stage": {"type": "string", "description": "Substring match on deal stage, e.g. 'Negotiations'"},
            },
        },
    },
    {
        "name": "get_work_orders",
        "description": (
            "Fetch project execution / billing data live from the monday.com Work "
            "Orders board. Optionally filter by sector or execution status. Always "
            "returns data_quality_notes — read and mention relevant caveats."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {"type": "string"},
                "execution_status": {"type": "string", "description": "e.g. Completed, Ongoing, Not Started, Pause / struck"},
            },
        },
    },
    {
        "name": "get_join_limitations",
        "description": (
            "Call this if a question requires matching a specific deal to its "
            "specific work order(s), or vice versa. Returns an explanation of why "
            "row-level joins between the two boards are not reliable in this dataset."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

TOOL_FUNCTIONS = {
    "get_deals": get_deals,
    "get_work_orders": get_work_orders,
    "get_join_limitations": get_join_limitations,
}
