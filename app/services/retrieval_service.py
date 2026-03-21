from __future__ import annotations

from typing import Any

from app.models.memory import MemoryItem, RetrievalResult
from app.services.cognee_service import CogneeService


class RetrievalService:
    def __init__(self, cognee_service: CogneeService) -> None:
        self._cognee_service = cognee_service

    @staticmethod
    def _rank_items(
        payloads: list[dict[str, Any]],
        query: str,
        file_paths: list[str] | None,
        top_k: int,
    ) -> list[RetrievalResult]:
        query_tokens = {token for token in query.lower().split() if token}
        desired_paths = {path.lower() for path in (file_paths or [])}
        ranked: list[RetrievalResult] = []
        for index, payload in enumerate(payloads):
            item = MemoryItem.model_validate(payload)
            haystack = f"{item.title} {item.content}".lower()
            overlap = len(query_tokens.intersection(haystack.split()))
            score = 1.0 / (index + 1) + overlap * 0.2
            reason_bits = ["semantic Cognee match"]
            if desired_paths and desired_paths.intersection({path.lower() for path in item.file_paths}):
                score += 0.3
                reason_bits.append("file path match")
            if overlap:
                reason_bits.append(f"{overlap} query token matches")
            ranked.append(
                RetrievalResult(
                    item=item,
                    score=round(score, 4),
                    reason=", ".join(reason_bits),
                )
            )
        ranked.sort(key=lambda result: result.score, reverse=True)
        return ranked[:top_k]

    async def search(
        self,
        *,
        project_id: str,
        query: str,
        top_k: int,
        file_paths: list[str] | None = None,
    ) -> list[RetrievalResult]:
        payloads = await self._cognee_service.search_memory(project_id, query, max(top_k * 2, top_k))
        return self._rank_items(payloads, query, file_paths, top_k)
