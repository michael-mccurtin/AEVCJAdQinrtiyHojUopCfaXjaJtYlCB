"""API tests for the FastAPI layer.

The query handler is swapped via FastAPI's dependency_overrides, so these tests
exercise routing, validation, and serialisation without any real LLM/DB calls.
"""

import pytest
from fastapi.testclient import TestClient

from app.llm.query_router import Outcome, RouteResult
from app.main import app, get_router


@pytest.fixture
def client():
    """A TestClient with the query handler stubbed to echo its inputs."""

    def fake_router(message, history):
        reply = f"reply to: {message} (history={len(history)})"
        return RouteResult(reply=reply, outcome=Outcome.OK)

    app.dependency_overrides[get_router] = lambda: fake_router
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_returns_reply(client):
    response = client.post("/chat", json={"message": "Tell me about Inception"})
    assert response.status_code == 200
    assert response.json() == {
        "reply": "reply to: Tell me about Inception (history=0)",
        "outcome": "ok",
    }


def test_chat_passes_history(client):
    response = client.post(
        "/chat",
        json={
            "message": "Who directed it?",
            "history": [
                {"role": "user", "content": "Tell me about Inception"},
                {"role": "assistant", "content": "It's a 2010 film."},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["reply"].endswith("(history=2)")


def test_chat_rejects_empty_message(client):
    response = client.post("/chat", json={"message": ""})
    assert response.status_code == 422  # min_length=1 violated


def test_chat_rejects_bad_history_role(client):
    response = client.post(
        "/chat",
        json={"message": "hi", "history": [{"role": "system", "content": "x"}]},
    )
    assert response.status_code == 422  # role must be user | assistant


def test_chat_llm_failure_maps_to_503():
    """A failure outcome surfaces as 5xx, with the friendly message in the body."""

    def failing_router(message, history):
        return RouteResult(reply="upstream is down", outcome=Outcome.LLM_ERROR)

    app.dependency_overrides[get_router] = lambda: failing_router
    try:
        with TestClient(app) as test_client:
            response = test_client.post("/chat", json={"message": "hi"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"reply": "upstream is down", "outcome": "llm_error"}
