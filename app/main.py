"""FastAPI entry point for the movie assistant.

Run locally with:
    uv run uvicorn app.main:app --reload

Interactive API docs are served at /docs.
"""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response, status

from app.config import settings
from app.llm.query_router import (
    LLM_ERROR_MESSAGE,
    LOOKUP_ERROR_MESSAGE,
    Outcome,
    RouteResult,
    get_client,
    route_query,
)
from app.models import ChatRequest, ChatResponse

log = logging.getLogger(__name__)

# Successful resolutions (answer / off-topic reject) are 200; dependency and
# internal failures surface as 5xx so clients, monitoring etc. can tell a real
# failure from a normal reply. The friendly user-facing message is still carried in the body.
STATUS_BY_OUTCOME = {
    Outcome.OK: status.HTTP_200_OK,
    Outcome.REJECTED: status.HTTP_200_OK,
    Outcome.LLM_ERROR: status.HTTP_503_SERVICE_UNAVAILABLE,
    Outcome.LOOKUP_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure logging and construct the LLM client at startup."""
    logging.basicConfig(level=settings.log_level)
    get_client()  # construct the shared client now so the first request isn't slow
    log.info("Movie assistant API ready (model=%s)", settings.llm_chat_model)
    yield


tags_metadata = [
    {"name": "chat", "description": "Ask the assistant movie questions."},
    {"name": "system", "description": "Operational endpoints (health checks)."},
]

app = FastAPI(
    title="Movie Assistant API",
    description="Conversational agent answering movie questions over the TMDB 5000 "
    "dataset, combining SQL retrieval with LLM responses.",
    version="0.1.0",
    openapi_tags=tags_metadata,
    contact={"name": "Movie Assistant", "url": "https://example.com"},
    lifespan=lifespan,
)


def get_router() -> Callable[..., str]:
    """Provide the query handler. Overridable in tests via dependency_overrides."""
    return route_query


@app.get("/health", tags=["system"], summary="Liveness check")
def health() -> dict[str, str]:
    """Return 200 with a static body once the service is up."""
    return {"status": "ok"}


@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["chat"],
    summary="Answer a movie question",
    responses={
        200: {
            "description": "A movie answer, or a reply declining an off-topic question.",
            "content": {
                "application/json": {
                    "example": {
                        "reply": '"Pulp Fiction" was directed by Quentin Tarantino.',
                        "outcome": Outcome.OK.value,
                    }
                }
            },
        },
        503: {
            "model": ChatResponse,
            "description": "The LLM service is unavailable. The body carries a "
            "friendly retry message.",
            "content": {
                "application/json": {
                    "example": {
                        "reply": LLM_ERROR_MESSAGE,
                        "outcome": Outcome.LLM_ERROR.value,
                    }
                }
            },
        },
        500: {
            "model": ChatResponse,
            "description": "The query could not be processed. The body carries a "
            "friendly fallback message.",
            "content": {
                "application/json": {
                    "example": {
                        "reply": LOOKUP_ERROR_MESSAGE,
                        "outcome": Outcome.LOOKUP_ERROR.value,
                    }
                }
            },
        },
    },
)
def chat(
    request: ChatRequest,
    response: Response,
    router: Callable[..., RouteResult] = Depends(get_router),
) -> ChatResponse:
    """Answer a movie question, optionally in the context of prior turns."""
    # route_query never raises: it returns a reply plus an Outcome. Successful
    # outcomes (an answer, or declining an off-topic question) are 200; the
    # friendly reply is sent in the body even on a 5xx, so the client always has
    # something to show.
    history = [turn.model_dump() for turn in request.history]
    result = router(request.message, history)
    response.status_code = STATUS_BY_OUTCOME[result.outcome]
    return ChatResponse(reply=result.reply, outcome=result.outcome)
