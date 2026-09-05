"""LibertAI Avatar API.

Assembles the app: storage, the seeded examples, and the routers for chat, scenarios, the
MCP registry, speech synthesis and transcription.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.admin import is_protected
from apps.api.chat import router as chat_router
from apps.api.db import migrate
from apps.api.mcp_registry import router as mcp_router
from apps.api.scenarios import router as scenarios_router
from apps.api.seed import seed
from apps.api.stt import router as stt_router
from apps.api.tts import router as tts_router

load_dotenv("apps/api/.env")

logger = logging.getLogger("avatar.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate()
    seed()
    if not is_protected():
        logger.warning(
            "ADMIN_TOKEN is not set: scenario and MCP editing endpoints are open. "
            "Set it before exposing this API to a network."
        )
    yield


app = FastAPI(title="LibertAI Avatar API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_credentials=False,
    # The admin UI edits scenarios and servers with PUT and DELETE.
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(tts_router)
app.include_router(scenarios_router)
app.include_router(mcp_router)
app.include_router(stt_router)


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "admin_protected": is_protected()}
