"""Request and response schemas for the movie assistant API."""

from typing import Literal

from pydantic import BaseModel, Field

from app.llm.query_router import Outcome


class Message(BaseModel):
    """A single conversation turn, matching the OpenAI chat message shape."""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """A user question plus any prior turns for conversational context."""

    message: str = Field(
        ...,
        min_length=1,
        description="The user's movie-related question.",
        examples=["Who directed Pulp Fiction?"],
    )
    history: list[Message] = Field(
        default_factory=list, description="Prior conversation turns, oldest first."
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": "Who directed it?",
                    "history": [
                        {"role": "user", "content": "Tell me about Inception"},
                        {"role": "assistant", "content": "Inception is a 2010 film."},
                    ],
                }
            ]
        }
    }


class ChatResponse(BaseModel):
    """The assistant's reply, a machine-readable outcome, and the retrieval behind it.

    The HTTP status conveys the coarse signal (200 vs 5xx); `outcome` gives the
    finer-grained reason for client interpretation; `sql`/`results`/`total` expose
    the structured retrieval so a client can show the answer's source.
    """

    reply: str = Field(
        ...,
        description="The natural-language answer, or a friendly fallback message.",
        examples=['"Pulp Fiction" was directed by Quentin Tarantino.'],
    )
    outcome: Outcome = Field(
        ...,
        description="How the query resolved: ok, rejected, llm_error, or lookup_error.",
        examples=[Outcome.OK],
    )
    sql: str | None = Field(
        default=None,
        description="The SQL the assistant ran, if any (null for off-topic/failed queries).",
    )
    results: list[dict] = Field(
        default_factory=list,
        description="The rows retrieved and used to ground the reply.",
    )
    total: int | None = Field(
        default=None,
        description="Total rows matching the query ignoring LIMIT, when known.",
    )
