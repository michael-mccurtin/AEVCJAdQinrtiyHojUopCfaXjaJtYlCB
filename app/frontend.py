"""Streamlit chat UI for the movie assistant.

Talks to the FastAPI backend over HTTP (keeping the UI decoupled from the core).
Start the API first, then launch this:

    uv run uvicorn app.main:app --reload          # in one terminal
    uv run streamlit run app/frontend.py          # in another

Point at a non-default API with the MOVIE_API_URL environment variable.
"""

import os

import httpx
import streamlit as st

API_URL = os.getenv("MOVIE_API_URL", "http://localhost:8000")
REQUEST_TIMEOUT = 60  # the pipeline makes up to three LLM calls

st.set_page_config(page_title="Movie Assistant", page_icon="🎬")

if "messages" not in st.session_state:
    st.session_state.messages = []

st.title("🎬 Movie Assistant")
intro, reset = st.columns([4, 1])
intro.caption("Ask about movies: actors, directors, genres, recommendations and more.")
if reset.button("🗑️ New chat", help="Clear the conversation and start fresh"):
    st.session_state.messages = []
    st.rerun()


def ask_api(message: str, history: list[dict]) -> dict:
    """Send a turn to the API and return the parsed response.

    Returns reply, sql, results, total, and ok (False on a 5xx or connection
    failure, so the UI can show the turn as degraded).
    """
    try:
        response = httpx.post(
            f"{API_URL}/chat",
            json={"message": message, "history": history},
            timeout=REQUEST_TIMEOUT,
        )
        data = response.json()
        return {
            "reply": data.get("reply", ""),
            "sql": data.get("sql"),
            "results": data.get("results", []),
            "total": data.get("total"),
            "ok": response.status_code < 500,
        }
    except httpx.HTTPError:
        return {
            "reply": f"Couldn't reach the assistant at {API_URL}. Is the API running?",
            "sql": None,
            "results": [],
            "total": None,
            "ok": False,
        }


def render_source(turn: dict) -> None:
    """Show the SQL and retrieved rows behind an answer in a collapsible panel."""
    if not turn.get("sql"):
        return
    with st.expander("🔍 Source"):
        st.caption("Generated SQL")
        st.code(turn["sql"], language="sql")
        rows = turn.get("results", [])
        total = turn.get("total")
        if total is not None and total > len(rows):
            st.caption(f"Showing {len(rows)} of {total} matching rows")
        else:
            st.caption(f"{len(rows)} row(s) retrieved")
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)


def render_turn(turn: dict) -> None:
    """Render one chat turn, with a source panel for grounded answers."""
    with st.chat_message(turn["role"]):
        if turn.get("ok") is False:
            st.warning(turn["content"])
        else:
            st.markdown(turn["content"])
        if turn["role"] == "assistant":
            render_source(turn)


# Replay the conversation so far.
for turn in st.session_state.messages:
    render_turn(turn)

# Handle a new turn. Render the user message immediately (before the blocking API
# call) so it appears straight away instead of vanishing behind the spinner.
if prompt := st.chat_input("Ask about a movie..."):
    history = [
        {"role": m["role"], "content": m["content"]} for m in st.session_state.messages
    ]
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            data = ask_api(prompt, history)
        if data["ok"]:
            st.markdown(data["reply"])
        else:
            st.warning(data["reply"])
        render_source(data)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": data["reply"],
            "ok": data["ok"],
            "sql": data["sql"],
            "results": data["results"],
            "total": data["total"],
        }
    )
