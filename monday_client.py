"""
Thin client for the monday.com GraphQL API (v2).

Design notes (see DECISION_LOG.md for the full reasoning):
- We read column *titles*, not raw column ids, and key every returned row by
  title. monday.com auto-generates opaque column ids (e.g. "text_mkr2x1a9")
  at import time that differ per-board-per-import. Keying by title makes the
  rest of the pipeline stable even if someone re-imports the boards.
- Everything is fetched live via items_page (cursor-paginated). Nothing from
  the original CSVs is embedded in this codebase.
"""

from __future__ import annotations
import time
from typing import Any

import requests

MONDAY_API_URL = "https://api.monday.com/v2"
PAGE_SIZE = 100
MAX_RETRIES = 3


class MondayAPIError(RuntimeError):
    pass


def _post(query: str, variables: dict, api_token: str) -> dict:
    headers = {
        "Authorization": api_token,
        "Content-Type": "application/json",
        "API-Version": "2024-10",
    }
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                MONDAY_API_URL,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
            continue

        if resp.status_code == 429:
            # rate limited — back off and retry
            time.sleep(2 * (attempt + 1))
            continue

        if resp.status_code >= 500:
            last_err = MondayAPIError(f"monday.com server error {resp.status_code}")
            time.sleep(1.5 * (attempt + 1))
            continue

        data = resp.json()
        if "errors" in data:
            raise MondayAPIError(str(data["errors"]))
        return data

    raise MondayAPIError(f"monday.com API unreachable after {MAX_RETRIES} attempts: {last_err}")


def get_board_columns(board_id: str, api_token: str) -> dict[str, str]:
    """Return {column_id: column_title} for a board."""
    query = """
    query ($boardId: [ID!]) {
      boards(ids: $boardId) {
        columns { id title type }
      }
    }
    """
    data = _post(query, {"boardId": [str(board_id)]}, api_token)
    boards = data["data"]["boards"]
    if not boards:
        raise MondayAPIError(f"Board {board_id} not found or not accessible with this token.")
    return {c["id"]: c["title"] for c in boards[0]["columns"]}


def get_board_items(board_id: str, api_token: str) -> list[dict[str, Any]]:
    """
    Fetch every item on a board, keyed by human-readable column title.
    Also includes '_item_id' and '_item_name' (monday's built-in name column).
    """
    column_titles = get_board_columns(board_id, api_token)

    items: list[dict[str, Any]] = []
    cursor = None

    while True:
        query = """
        query ($boardId: [ID!], $cursor: String, $limit: Int!) {
          boards(ids: $boardId) {
            items_page(limit: $limit, cursor: $cursor) {
              cursor
              items {
                id
                name
                column_values { id text value }
              }
            }
          }
        }
        """
        variables = {"boardId": [str(board_id)], "cursor": cursor, "limit": PAGE_SIZE}
        data = _post(query, variables, api_token)
        page = data["data"]["boards"][0]["items_page"]

        for item in page["items"]:
            row: dict[str, Any] = {
                "_item_id": item["id"],
                "_item_name": item["name"],
            }
            for cv in item["column_values"]:
                title = column_titles.get(cv["id"], cv["id"])
                row[title] = cv["text"]
            items.append(row)

        cursor = page.get("cursor")
        if not cursor:
            break

    return items


def test_connection(api_token: str) -> str:
    """Returns the connected account's name, or raises MondayAPIError."""
    query = "query { me { name account { name } } }"
    data = _post(query, {}, api_token)
    me = data["data"]["me"]
    return f"{me['name']} ({me['account']['name']})"
