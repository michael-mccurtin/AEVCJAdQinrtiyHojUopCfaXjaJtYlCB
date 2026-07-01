"""Thin OpenAI wrapper for the three-stage movie query pipeline.

Each public method maps to one stage: classify the user's intent, generate a
read-only SQL query, and turn query results into a conversational reply. Failures
surface as exceptions — OpenAI's APIError, a ValidationError from the SQL safety
check, or LLMError for an empty/refused completion — for the caller (query_router)
to translate into user-facing messages.
"""

import json
import logging
from typing import Literal, TypeVar

import sqlparse
from openai import OpenAI
from pydantic import BaseModel, field_validator

from app.config import settings
from app.llm.prompts import (
    CLASSIFIER_SYSTEM_PROMPT,
    RESPONSE_GENERATOR_SYSTEM_PROMPT,
    SQL_GENERATOR_SYSTEM_PROMPT,
)

log = logging.getLogger(__name__)

# Structured-output schemas are pydantic models; T preserves the concrete type
# through the generic _chat_structured helper.
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when the model returns no usable output: an empty parse or a refusal."""


class ClassificationResult(BaseModel):
    """Structured output of the classify stage: the routing decision and its rationale."""

    intent: Literal["sql", "reject"]
    reason: str


class GeneratedSQL(BaseModel):
    """Structured output of the SQL stage: a single, validated SELECT statement."""

    sql: str

    @field_validator("sql")
    @classmethod
    def must_be_single_select(cls, value: str) -> str:
        """Reject anything that isn't exactly one SELECT statement.

        The core safety check for LLM-generated SQL. With the read-only
        connection, it blocks writes and multi-statement injection.
        `sqlparse.get_type()` returns a statement's leading keyword ('SELECT',
        'INSERT', ...); the truthiness filter drops the empty trailing statement
        a closing semicolon produces, i.e. "SELECT 1;" counts as one statement.
        """
        statements = [s for s in sqlparse.parse(value) if s.get_type()]
        if len(statements) != 1 or statements[0].get_type() != "SELECT":
            raise ValueError("Only a single SELECT statement is permitted")
        return value


class LLMClient:
    """Wrapper around the OpenAI Chat Completions API for the movie query pipeline."""

    def __init__(self) -> None:
        """Construct the client. Requires settings.openai_api_key to be set."""
        if not settings.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. It is required to use the LLM features "
                "(the ingest script does not need it)."
            )
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.llm_chat_model

    def classify(
        self, query: str, history: list[dict] | None = None
    ) -> ClassificationResult:
        """Classify a user query as 'sql' (movie-related) or 'reject' (off-topic).

        Args:
            query: The user's latest message.
            history: Prior turns as {role, content} dicts, for context-dependent
                questions.

        Raises:
            openai.APIError: on a network, rate-limit, or API failure.
            LLMError: if the model refuses or returns no parseable output.
        """
        messages = self._build_messages(CLASSIFIER_SYSTEM_PROMPT, query, history)
        return self._chat_structured(messages, ClassificationResult)

    def generate_sql(self, query: str, history: list[dict] | None = None) -> str:
        """Generate a single validated SQLite SELECT for a natural-language query.

        Args:
            query: The user's latest message.
            history: Prior turns, used to resolve references like "who directed it?".

        Raises:
            openai.APIError: on a network, rate-limit, or API failure.
            pydantic.ValidationError: if the model emits non-SELECT SQL.
            LLMError: if the model refuses or returns no parseable output.
        """
        return self._chat_structured(
            self._build_messages(SQL_GENERATOR_SYSTEM_PROMPT, query, history),
            GeneratedSQL,
        ).sql

    def generate_response(
        self,
        query: str,
        results: list[dict],
        history: list[dict] | None = None,
        total: int | None = None,
    ) -> str:
        """Turn SQL query results into a grounded, conversational reply.

        Args:
            query: The user's question.
            results: Rows from execute_query, serialised as JSON context.
            history: Prior turns, for conversational continuity.
            total: Total number of matching rows (ignoring LIMIT). When it
                exceeds the rows shown, the reply discloses that this is a
                partial list rather than implying it is exhaustive.

        Raises:
            openai.APIError: on a network, rate-limit, or API failure.
        """
        # Drop internal movie IDs so they don't leak into the user-facing reply.
        # (id stays in the SQL SELECT because it keeps DISTINCT correct for
        # same-titled films; it just isn't shown to the model here.)
        visible = [{k: v for k, v in row.items() if k != "id"} for row in results]
        context = json.dumps(visible, indent=2)
        note = ""
        if total is not None and total > len(results):
            note = (
                f"\n\nNote: {total} movies match this query, but only the first "
                f"{len(results)} are shown. Tell the user the total ({total}) and "
                "that this is a partial list they can ask to see in full or narrow down."
            )
        user_content = f"Question: {query}\n\nData:\n{context}{note}"
        messages = self._build_messages(
            RESPONSE_GENERATOR_SYSTEM_PROMPT, user_content, history
        )
        return self._chat_text(messages)

    @staticmethod
    def _build_messages(
        system_prompt: str, user_content: str, history: list[dict] | None
    ) -> list[dict]:
        """Assemble the messages list: system prompt, prior history, then the new turn."""
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_content})
        return messages

    def _chat_text(self, messages: list[dict], temperature: float = 0.7) -> str:
        """Return the free-text content of a chat completion.

        content is None on a refusal or tool-only completion, so coalescing to ""
        before stripping avoids an AttributeError.
        """
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
        )
        return (response.choices[0].message.content or "").strip()

    def _chat_structured(
        self, messages: list[dict], schema: type[T], temperature: float = 0.0
    ) -> T:
        """Return a parsed pydantic model from a structured-output completion.

        Defaults to temperature 0: classification and SQL generation are
        deterministic tasks. Reproducibility matters more than variety here.

        Raises:
            LLMError: if the model refuses or returns no parseable output.
        """
        response = self._client.chat.completions.parse(
            model=self._model,
            messages=messages,
            response_format=schema,
            temperature=temperature,
        )
        message = response.choices[0].message
        if message.refusal:
            raise LLMError(f"Model refused the request: {message.refusal}")
        if message.parsed is None:
            raise LLMError("Model returned no parseable structured output")
        return message.parsed
