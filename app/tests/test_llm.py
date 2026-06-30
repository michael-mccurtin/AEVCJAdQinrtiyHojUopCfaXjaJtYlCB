"""Tests for the LLM layer: the SQL safety validator and the query router.

Validator tests exercise the security boundary.
Router tests inject a fake client so routing logic can be verified without a
live API key or network calls.
"""

import httpx
import pytest
from openai import APIError
from pydantic import ValidationError

from app.llm import query_router
from app.llm.client import ClassificationResult, GeneratedSQL

VALID_SELECTS = [
    "SELECT id, title FROM movies",
    "SELECT id, title FROM movies WHERE year = 1999 LIMIT 10",
    "SELECT m.id, m.title FROM movies m JOIN genres g ON g.movie_id = m.id",
]

REJECTED_STATEMENTS = [
    "DROP TABLE movies",
    "DELETE FROM movies WHERE id = 1",
    "INSERT INTO movies (id, title) VALUES (1, 'x')",
    "UPDATE movies SET title = 'x' WHERE id = 1",
    "SELECT id FROM movies; DROP TABLE movies",  # stacked statements
]

# Validator tests


@pytest.mark.parametrize("sql", VALID_SELECTS)
def test_validator_accepts_single_select(sql):
    assert GeneratedSQL(sql=sql).sql == sql


@pytest.mark.parametrize("sql", REJECTED_STATEMENTS)
def test_validator_rejects_non_select(sql):
    with pytest.raises(ValidationError):
        GeneratedSQL(sql=sql)


# Router tests


def _api_error() -> APIError:
    """Build a realistic OpenAI APIError to simulate an upstream failure."""
    return APIError(
        "upstream down", request=httpx.Request("POST", "http://x"), body=None
    )


class FakeLLMClient:
    """Fake LLMClient that records calls and returns canned values.

    generate_sql runs the real GeneratedSQL validator, so passing an unsafe `sql`
    raises ValidationError exactly as the production client would when the model
    returns a non-SELECT.
    """

    def __init__(
        self, intent="sql", sql="SELECT id, title FROM movies", classify_error=None
    ):
        self._intent = intent
        self._sql = sql
        self._classify_error = classify_error
        self.generate_sql_called = False

    def classify(self, query, history=None):
        if self._classify_error:
            raise self._classify_error
        return ClassificationResult(intent=self._intent, reason="test")

    def generate_sql(self, query, history=None):
        self.generate_sql_called = True
        return GeneratedSQL(sql=self._sql).sql

    def generate_response(self, query, results, history=None):
        return f"Found {len(results)} result(s)."


def test_reject_short_circuits_before_sql():
    """A rejected query returns the rejection message without generating SQL.

    generate_sql_called staying False also proves the DB is never reached, since
    SQL generation precedes execution in the pipeline.
    """
    client = FakeLLMClient(intent="reject")

    result = query_router.route_query("what is the capital of France?", client=client)

    assert result.reply == query_router.REJECTION_MESSAGE
    assert result.outcome == query_router.Outcome.REJECTED
    assert client.generate_sql_called is False


def test_llm_failure_returns_friendly_message():
    """An upstream LLM error is caught and reported as an LLM_ERROR outcome."""
    client = FakeLLMClient(classify_error=_api_error())

    result = query_router.route_query("anything", client=client)

    assert result.reply == query_router.LLM_ERROR_MESSAGE
    assert result.outcome == query_router.Outcome.LLM_ERROR


def test_invalid_generated_sql_returns_friendly_message():
    """If the model emits a non-SELECT, the validator raises, resulting in
    graceful degradation (a LOOKUP_ERROR outcome) rather than crashing."""
    client = FakeLLMClient(intent="sql", sql="DROP TABLE movies")

    result = query_router.route_query("delete everything", client=client)

    assert result.reply == query_router.LOOKUP_ERROR_MESSAGE
    assert result.outcome == query_router.Outcome.LOOKUP_ERROR
