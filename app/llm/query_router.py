import logging
import sqlite3
from enum import Enum

from openai import APIError
from pydantic import BaseModel, ValidationError

from app.db.db import count_rows, execute_query
from app.llm.client import LLMClient, LLMError

log = logging.getLogger(__name__)

REJECTION_MESSAGE = (
    "I can only answer questions about movies. Please ask me something movie-related!"
)
LLM_ERROR_MESSAGE = "I'm having trouble reaching my reasoning engine right now. Please try again shortly."
LOOKUP_ERROR_MESSAGE = (
    "I couldn't look that information up. Could you try rephrasing your question?"
)


class Outcome(str, Enum):
    """How a query was resolved.

    OK and REJECTED are successful resolutions (the pipeline did its job);
    LLM_ERROR and LOOKUP_ERROR are failures. The HTTP layer maps the failure
    outcomes to 5xx while still returning the friendly reply in the body.
    """

    OK = "ok"
    REJECTED = "rejected"
    LLM_ERROR = "llm_error"
    LOOKUP_ERROR = "lookup_error"


class RouteResult(BaseModel):
    """A user-facing reply plus the retrieval that produced it.

    sql and results expose the structured-retrieval step for transparency (the
    frontend shows them as the answer's source); both are empty for off-topic or
    failed queries that never reached the database.
    """

    reply: str
    outcome: Outcome
    sql: str | None = None
    results: list[dict] = []
    total: int | None = None  # total matching rows ignoring LIMIT (for "10 of 27")


# Lazily-instantiated default client. Importing this module (e.g. in tests or
# at app startup) will not require an API key or open a network client.
_default_client: LLMClient | None = None


def get_client() -> LLMClient:
    """Return the process-wide LLMClient, creating it on first use."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


def route_query(
    query: str,
    history: list[dict] | None = None,
    client: LLMClient | None = None,
) -> RouteResult:
    """Classify a query, retrieve relevant data, and return a conversational reply.

    Never raises: each failure is caught and returned as a `RouteResult` with a
    failure `Outcome`, so the caller decides how to surface it (the API maps the
    outcome to an HTTP status). Off-topic and empty-result queries are normal
    successful outcomes, not failures.

    Args:
        query: The user's natural language question.
        history: Prior conversation turns as a list of role/content dicts.
        client: LLM client to use. Defaults to the shared lazy singleton;
            injectable so tests can supply a fake without a live API key.
    """
    client = client or get_client()

    try:
        classification = client.classify(query, history)
        log.info(
            "Classified as %r (reason: %s): %s",
            classification.intent,
            classification.reason,
            query,
        )

        if classification.intent == "reject":
            return RouteResult(reply=REJECTION_MESSAGE, outcome=Outcome.REJECTED)

        sql = client.generate_sql(query, history)
        # Collapse whitespace so the whole query stays on one log line (the model often returns it multi-line).
        log.info("Generated SQL: %s", " ".join(sql.split()))

        results = execute_query(sql)
        log.info("Query returned %d results", len(results))

        # Count total matching rows ignoring LIMIT, so the response stage can disclose
        # a partial list ("showing 10 of 27") instead of implying it is complete.
        # Guarded: a count failure must not discard an otherwise good result.
        try:
            total = count_rows(sql)
        except sqlite3.Error:
            total = len(results)
        reply = client.generate_response(query, results, history, total=total)
        return RouteResult(
            reply=reply, outcome=Outcome.OK, sql=sql, results=results, total=total
        )
    except (APIError, LLMError) as e:
        # Network/rate-limit/API failures, or a model refusal/empty completion.
        log.error("LLM call failed: %s", e)
        return RouteResult(reply=LLM_ERROR_MESSAGE, outcome=Outcome.LLM_ERROR)
    except (sqlite3.Error, ValidationError) as e:
        # A valid-but-wrong SELECT, or model output that failed SQL validation.
        log.error("Query handling failed: %s", e)
        return RouteResult(reply=LOOKUP_ERROR_MESSAGE, outcome=Outcome.LOOKUP_ERROR)
    except Exception:
        # Catch-all so the API never surfaces an unhandled 500 to the user.
        log.exception("Unexpected error handling query: %s", query)
        return RouteResult(reply=LOOKUP_ERROR_MESSAGE, outcome=Outcome.LOOKUP_ERROR)
