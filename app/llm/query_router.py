import logging
import sqlite3

from openai import APIError
from pydantic import ValidationError

from app.db.db import execute_query
from app.llm.client import LLMClient, LLMError

log = logging.getLogger(__name__)

REJECTION_MESSAGE = (
    "I can only answer questions about movies. Please ask me something movie-related!"
)
LLM_ERROR_MESSAGE = "I'm having trouble reaching my reasoning engine right now. Please try again shortly."
LOOKUP_ERROR_MESSAGE = (
    "I couldn't look that information up. Could you try rephrasing your question?"
)

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
) -> str:
    """Classify a query, retrieve relevant data, and return a conversational response.

    Args:
        query: The user's natural language question.
        history: Prior conversation turns as a list of role/content dicts.
        client: LLM client to use. Defaults to the shared lazy singleton;
            injectable so tests can supply a fake without a live API key.

    Returns:
        A conversational response string, or a friendly fallback message if the
        query is off-topic or a stage of the pipeline fails.
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
            return REJECTION_MESSAGE

        sql = client.generate_sql(query, history)
        log.debug("Generated SQL: %s", sql)

        results = execute_query(sql)
        log.info("Query returned %d results", len(results))

        return client.generate_response(query, results, history)
    except (APIError, LLMError) as e:
        # Network/rate-limit/API failures, or a model refusal/empty completion.
        log.error("LLM call failed: %s", e)
        return LLM_ERROR_MESSAGE
    except (sqlite3.Error, ValidationError) as e:
        # A valid-but-wrong SELECT, or model output that failed SQL validation.
        log.error("Query handling failed: %s", e)
        return LOOKUP_ERROR_MESSAGE
    except Exception:
        # Catch-all so the API never surfaces an unhandled 500 to the user.
        log.exception("Unexpected error handling query: %s", query)
        return LOOKUP_ERROR_MESSAGE
