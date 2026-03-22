from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Literal
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.core.config import Settings
from app.models.memory import RetrievalResult


@dataclass(slots=True)
class ChatAnswer:
    answer: str
    mode: Literal["llm", "fallback"]


class ChatService:
    def __init__(self, settings: Settings, *, timeout_seconds: float = 20.0) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds

    async def answer(self, *, query: str, results: list[RetrievalResult]) -> ChatAnswer:
        if not results:
            return ChatAnswer(
                answer="I could not find relevant stored memory for that question.",
                mode="fallback",
            )
        if not self._can_use_llm():
            return ChatAnswer(answer=self._fallback_answer(results), mode="fallback")
        try:
            answer = await asyncio.to_thread(self._request_openai_answer, query, results)
        except (RuntimeError, OSError, TimeoutError, ValueError, urllib_error.URLError):
            return ChatAnswer(answer=self._fallback_answer(results), mode="fallback")
        if not answer:
            return ChatAnswer(answer=self._fallback_answer(results), mode="fallback")
        return ChatAnswer(answer=answer, mode="llm")

    def _can_use_llm(self) -> bool:
        return self._settings.has_llm_api_key() and self._settings.llm_provider.lower() == "openai"

    def _request_openai_answer(self, query: str, results: list[RetrievalResult]) -> str:
        context_block = self._context_block(results)
        payload = {
            "model": self._settings.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer the user's question using only the provided project memory. "
                        "Be concise, direct, and grounded in the retrieved memory. "
                        "If the memory is insufficient, say so explicitly and do not invent facts."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{query}\n\n"
                        f"Project memory:\n{context_block}\n\n"
                        "Return only the answer for the user."
                    ),
                },
            ],
            "temperature": 0.2,
        }
        req = urllib_request.Request(
            url="https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=self._timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("LLM returned no choices")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not isinstance(content, str):
            raise RuntimeError("LLM returned a non-text response")
        return content.strip()

    @staticmethod
    def _normalize_text(value: str, *, limit: int = 280) -> str:
        compact = " ".join(value.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    def _context_block(self, results: list[RetrievalResult]) -> str:
        lines: list[str] = []
        for index, result in enumerate(results[:5], start=1):
            item = result.item
            file_hint = f" [{', '.join(item.file_paths[:2])}]" if item.file_paths else ""
            lines.append(
                f"{index}. {item.title}{file_hint}\n"
                f"Type: {item.type}\n"
                f"Reason: {result.reason}\n"
                f"Content: {self._normalize_text(item.content, limit=500)}"
            )
        return "\n\n".join(lines)

    def _fallback_answer(self, results: list[RetrievalResult]) -> str:
        snippets: list[str] = []
        seen: set[str] = set()
        for result in results:
            snippet = self._normalize_text(result.item.content)
            if not snippet:
                continue
            key = snippet.casefold()
            if key in seen:
                continue
            seen.add(key)
            snippets.append(snippet)
            if len(snippets) == 3:
                break
        if not snippets:
            return "I found matching memory, but it did not contain a usable answer."
        if len(snippets) == 1:
            return f"Based on stored memory, {snippets[0]}"
        return "Based on stored memory:\n- " + "\n- ".join(snippets)
