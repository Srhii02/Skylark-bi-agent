"""
Skylark Drones — monday.com Business Intelligence Agent
Entry point for Streamlit Community Cloud (or `streamlit run app.py` locally).
"""

import os
import streamlit as st
from dotenv import load_dotenv

from backend import monday_client
from backend.agent import run_agent

load_dotenv()

st.set_page_config(page_title="Skylark BI Agent", page_icon="📊", layout="centered")


def get_secret(key: str) -> str | None:
    # Supports Streamlit Cloud's secrets manager, plain env vars, or a local .env
    if key in st.secrets:
        return st.secrets[key]
    return os.environ.get(key)


MONDAY_API_TOKEN = get_secret("MONDAY_API_TOKEN")
DEALS_BOARD_ID = get_secret("MONDAY_DEALS_BOARD_ID")
WORK_ORDERS_BOARD_ID = get_secret("MONDAY_WORK_ORDERS_BOARD_ID")
ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY")

st.title("📊 Skylark Drones — BI Agent")
st.caption("Ask about pipeline, revenue, sectoral performance, or operations across your monday.com boards.")

missing = [
    name for name, val in [
        ("MONDAY_API_TOKEN", MONDAY_API_TOKEN),
        ("MONDAY_DEALS_BOARD_ID", DEALS_BOARD_ID),
        ("MONDAY_WORK_ORDERS_BOARD_ID", WORK_ORDERS_BOARD_ID),
        ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    ] if not val
]
if missing:
    st.error(
        "Missing configuration: " + ", ".join(missing) +
        ".\n\nSet these in `.streamlit/secrets.toml` (or as environment variables) — "
        "see README.md for setup instructions."
    )
    st.stop()

with st.sidebar:
    st.subheader("Connection")
    if st.button("Test monday.com connection"):
        try:
            who = monday_client.test_connection(MONDAY_API_TOKEN)
            st.success(f"Connected as {who}")
        except Exception as e:  # noqa: BLE001
            st.error(f"Connection failed: {e}")
    st.divider()
    st.caption(
        "This agent reads two boards live on every query round: Deals and "
        "Work Orders. Nothing is cached from the original CSVs — if you edit "
        "the boards, the agent sees the change (cache refreshes every 3 min)."
    )
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("e.g. How's our pipeline looking for the energy sector this quarter?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Checking the boards..."):
            try:
                reply = run_agent(
                    conversation=st.session_state.messages,
                    board_ids={"deals": DEALS_BOARD_ID, "work_orders": WORK_ORDERS_BOARD_ID},
                    monday_api_token=MONDAY_API_TOKEN,
                    anthropic_api_key=ANTHROPIC_API_KEY,
                )
            except Exception as e:  # noqa: BLE001
                reply = f"Something went wrong talking to monday.com or Claude: `{e}`"
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
