"""HTTP API for connecting a web chat interface to GU.

Run with: uvicorn api:app --reload --port 8000
"""

import asyncio
import logging
import os
import re
from typing import Literal, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from PORTALagent import (
    ENGLISH_LANGUAGE_INSTRUCTION,
    FRANCO_LANGUAGE_INSTRUCTION,
    agent,
    contains_arabic_script,
    parse_language_prefixed_message,
)


logger = logging.getLogger(__name__)
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
LanguagePreference = Literal["english", "franco_egyptian"]

LANGUAGE_INSTRUCTIONS: dict[LanguagePreference, str] = {
    "english": ENGLISH_LANGUAGE_INSTRUCTION,
    "franco_egyptian": FRANCO_LANGUAGE_INSTRUCTION,
}

app = FastAPI(
    title="GU API",
    version="1.0.0",
    description="Chat API for the GUC student portal assistant.",
)

# Supply a comma-separated FRONTEND_ORIGINS value in .env for production, e.g.
# FRONTEND_ORIGINS=https://chat.example.com
origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


class ChatRequest(BaseModel):
    """A single message submitted by the frontend."""

    message: str = Field(min_length=1, max_length=4_000)
    session_id: str | None = Field(default=None, max_length=80)
    language: LanguagePreference


class ChatResponse(BaseModel):
    """A reply plus the ID the frontend must preserve for the conversation."""

    session_id: str
    reply: str
    is_new_session: bool
    language: LanguagePreference


def _session_id(value: str | None) -> tuple[str, bool]:
    """Use a safe frontend ID or create a new conversation ID."""
    if value is None:
        return uuid4().hex, True
    if not SESSION_ID_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=422,
            detail="session_id may contain only letters, numbers, hyphens, and underscores.",
        )
    return value, False


def _invoke_agent(message: str, session_id: str, language: LanguagePreference) -> str:
    """Run the synchronous LangGraph agent with isolated per-chat memory."""
    result = agent.invoke(
        {"messages": [{
            "role": "user",
            "content": (
                f"[Language instruction: {LANGUAGE_INSTRUCTIONS[language]}]\n\n"
                f"Student request: {message.strip()}"
            ),
        }]},
        config={"configurable": {"thread_id": session_id}},
    )
    content = result["messages"][-1].content
    reply = content if isinstance(content, str) else str(content)
    if language == "franco_egyptian" and contains_arabic_script(reply):
        correction = agent.invoke(
            {"messages": [{
                "role": "user",
                "content": (
                    f"[Language instruction: {LANGUAGE_INSTRUCTIONS[language]}]\n\n"
                    "Rewrite your previous reply in Franco Egyptian using English "
                    "letters only. Do not use any Arabic characters; use English "
                    "for words you cannot write in Franco."
                ),
            }]},
            config={"configurable": {"thread_id": session_id}},
        )
        content = correction["messages"][-1].content
        reply = content if isinstance(content, str) else str(content)
    if contains_arabic_script(reply):
        return "Sorry, GU needs to rewrite that reply using English letters only. Please try again."
    return reply


@app.get("/api/health")
def health() -> dict[str, str]:
    """Lightweight readiness endpoint for the frontend or deployment platform."""
    return {"status": "ok", "service": "gu"}


@app.post("/api/chat", response_model=ChatResponse)
@app.post("/api/gu-assistant/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a student message and receive the assistant's Markdown-formatted reply."""
    session_id, is_new_session = _session_id(request.session_id)
    prefixed_language, student_message = parse_language_prefixed_message(request.message)
    if prefixed_language is None:
        raise HTTPException(
            status_code=422,
            detail="Start every message with 'english' or 'franco'.",
        )
    language = cast(LanguagePreference, prefixed_language)
    if language != request.language:
        selected_language = request.language
        return ChatResponse(
            session_id=session_id,
            reply=(
                "Wrong language. El toggle Franco, fa ektob franco bel English letters "
                "w ebda2 el message b franco."
                if selected_language == "franco_egyptian"
                else "Wrong language. The toggle is set to English; start your message with english and write in English."
            ),
            is_new_session=is_new_session,
            language=selected_language,
        )
    if not student_message:
        return ChatResponse(
            session_id=session_id,
            reply=(
                "Ekteb el so2al ba3d franco."
                if language == "franco_egyptian"
                else "Write your request after english."
            ),
            is_new_session=is_new_session,
            language=language,
        )
    try:
        reply = await asyncio.to_thread(_invoke_agent, student_message, session_id, language)
    except Exception:
        logger.exception("Chat request failed for session %s", session_id)
        raise HTTPException(
            status_code=503,
            detail="The assistant is temporarily unavailable. Please try again.",
        ) from None
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        is_new_session=is_new_session,
        language=language,
    )
