from __future__ import annotations

import os
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv("apps/api/.env")

LIBERTAI_BASE_URL = os.getenv("LIBERTAI_BASE_URL", "https://api.libertai.io").rstrip("/")
DEFAULT_MODEL = os.getenv("LIBERTAI_DEFAULT_MODEL", "hermes-3-8b-tee")


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=16000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)
    persona: str | None = Field(default=None, max_length=4000)
    model: str | None = Field(default=None, max_length=128)


class ChatResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str
    model: str


app = FastAPI(title="LibertAI Avatar API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    x_libertai_api_key: str | None = Header(default=None, alias="X-LibertAI-API-Key"),
) -> ChatResponse:
    api_key = x_libertai_api_key or os.getenv("LIBERTAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Missing LibertAI API key. Set LIBERTAI_API_KEY on the server or pass X-LibertAI-API-Key.",
        )

    messages = [message.model_dump() for message in request.messages]
    if request.persona:
        messages = [{"role": "system", "content": request.persona}, *messages]

    model = request.model or DEFAULT_MODEL
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{LIBERTAI_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=_extract_error_detail(exc.response),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LibertAI request failed: {exc}") from exc

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Unexpected LibertAI response shape.") from exc

    return ChatResponse(content=content, model=model)


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(data.get("detail"), str):
            return data["detail"]
    return response.text
