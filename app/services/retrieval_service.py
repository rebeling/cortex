from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.models.memory import MemoryItem, RetrievalResult
from app.services.cognee_service import CogneeService


class RetrievalService:
    def __init__(self, cognee_service: CogneeService) -> None:
        self._cognee_service = cognee_service

    @staticmethod
    def _string_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _decode_search_result(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, str):
            return None
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(value[start : end + 1])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _payload_to_item(payload: dict[str, Any]) -> MemoryItem:
        """Try to validate directly, otherwise build a synthetic MemoryItem from raw data."""
        try:
            return MemoryItem.model_validate(payload)
        except ValidationError:
            pass
        nested_payload = RetrievalService._decode_search_result(payload.get("search_result"))
        if nested_payload is not None:
            merged_payload = dict(nested_payload)
            for key in ("dataset_id", "dataset_name", "dataset_tenant_id"):
                if key in payload:
                    merged_payload[key] = payload[key]
            try:
                return MemoryItem.model_validate(merged_payload)
            except ValidationError:
                payload = merged_payload
        # Extract best-effort text from raw Cognee chunk
        text = ""
        for key in ("text", "content", "chunk", "raw_text", "chunk_data", "search_result"):
            if key in payload and isinstance(payload[key], str):
                text = payload[key]
                break
        if not text:
            text = str(payload)
        title = payload.get("title") or payload.get("chunk_id") or "search result"
        now = datetime.now(timezone.utc)
        return MemoryItem(
            id=RetrievalService._string_value(payload.get("id") or payload.get("chunk_id")) or str(uuid.uuid4()),
            project_id=RetrievalService._string_value(payload.get("project_id") or payload.get("dataset_id")) or "unknown",
            type="description",
            title=str(title)[:200],
            content=text,
            provenance="cognee_search",
            source_type="cognee_chunk",
            confidence=0.5,
            created_at=now,
            captured_at=now,
            extractor_version="retrieval-fallback",
            source_hash="",
            run_id="",
        )

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
            item = RetrievalService._payload_to_item(payload)
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
                    dataset_id=RetrievalService._string_value(payload.get("dataset_id")),
                    dataset_name=RetrievalService._string_value(payload.get("dataset_name")),
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
