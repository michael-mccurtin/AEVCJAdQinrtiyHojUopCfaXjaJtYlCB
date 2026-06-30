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
    """The assistant's conversational reply plus a machine-readable outcome.

    The HTTP status conveys the coarse signal (200 vs 5xx); `outcome` gives the
    finer-grained reason for client interpretation.
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
