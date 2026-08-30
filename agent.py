"""
The conversational agent: a Claude tool-use loop over the two monday.com
boards. Claude decides which board(s) to query, interprets founder-level
questions, and is instructed to surface data quality caveats rather than
present numbers as more certain than they are.
"""

from __future__ import annotations
import json
from typing import Any

import anthropic

from . import tools as agent_tools

MODEL = "claude-sonnet-5"
MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """You are Skylark Drones' internal Business Intelligence agent. \
Founders and executives ask you plain-language questions about the sales \
pipeline (Deals board) and project execution/billing (Work Orders board) on \
monday.com. You answer by calling tools to fetch live data — never invent \
numbers.

Rules:
1. Always use the tools to get data before answering a factual question. Never \
   answer from memory or assumption.
2. The two boards do NOT share a reliable row-level join key (different \
   customer-code schemes). If a question requires matching an individual deal \
   to an individual work order, call get_join_limitations and explain the \
   constraint plainly, then answer at the aggregate level you CAN support \
   (e.g. by sector, by owner code, by time period) instead of guessing a match.
3. The data is real-world messy: missing values, unparseable numbers, and a \
   small number of corrupted rows are dropped automatically before you see \
   the data. Every tool result includes data_quality_notes — read them, and \
   when they materially affect your answer's reliability (e.g. many rows \
   with missing deal value), say so briefly and plainly. Don't recite the \
   full report if it isn't relevant to the question.
4. If a founder's question is genuinely ambiguous (e.g. "this quarter" — \
   which quarter?), ask ONE brief clarifying question rather than guessing. \
   If it's ambiguous but you can reasonably assume something (e.g. "recent" \
   probably means last 90 days), state the assumption in one line and answer \
   anyway.
5. Give business insight, not just a number: pipeline health should mention \
   deal stage distribution or risk, not just a total. Revenue answers should \
   note what's billed vs. collected vs. outstanding where relevant.
6. Keep answers tight and executive-friendly: lead with the answer, then 1-3 \
   sentences of supporting context, then caveats if material. No long report \
   formatting — this is a conversation.
7. If asked to prepare something for a leadership update, produce a short, \
   copy-pasteable summary (bullet points, key metrics, notable risks) rather \
   than a wall of prose.
"""


def _run_tool(name: str, tool_input: dict, board_ids: dict, api_token: str) -> Any:
    fn = agent_tools.TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"Unknown tool {name}"}

    if name == "get_deals":
        return fn(board_ids["deals"], api_token, **tool_input)
    if name == "get_work_orders":
        return fn(board_ids["work_orders"], api_token, **tool_input)
    return fn()


def run_agent(
    conversation: list[dict],
    board_ids: dict,
    monday_api_token: str,
    anthropic_api_key: str,
) -> str:
    """
    conversation: list of {"role": "user"|"assistant", "content": str} — prior
    turns plus the newest user message already appended.
    Returns the assistant's final text reply.
    """
    client = anthropic.Anthropic(api_key=anthropic_api_key)

    messages: list[dict] = [
        {"role": m["role"], "content": m["content"]} for m in conversation
    ]

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            tools=agent_tools.TOOL_SCHEMAS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            text_parts = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_parts).strip() or "(no response)"

        # Assistant made one or more tool calls — execute them and continue the loop.
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                result = _run_tool(block.name, block.input, board_ids, monday_api_token)
                result_text = json.dumps(result, default=str)
            except Exception as e:  # noqa: BLE001 - surface API/data errors to the agent, not a crash
                result_text = json.dumps({"error": str(e)})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
            })

        messages.append({"role": "user", "content": tool_results})

    return "I wasn't able to finish gathering the data for this in time — could you narrow the question a bit?"
