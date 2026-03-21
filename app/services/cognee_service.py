from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.models.memory import MemoryItem

logger = logging.getLogger(__name__)


class CogneeUnavailableError(RuntimeError):
    """Raised when Cognee is not installed or not configured."""


class CogneeStorageError(RuntimeError):
    """Raised when Cognee storage or retrieval fails at runtime."""


class CogneeService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self._cognee = None
        self._search_type_chunks = None

    def _prepare_environment(self) -> None:
        if self._settings is None:
            return
        if not self._settings.has_llm_api_key():
            raise CogneeUnavailableError("LLM_API_KEY is not configured. Add it to .env or the process environment.")
        relative_vars = self._settings.relative_cognee_env_vars()
        if relative_vars:
            joined = ", ".join(relative_vars)
            raise CogneeUnavailableError(
                f"Cognee path variables must be absolute or omitted in .env: {joined}. "
                "Remove them to use Cortex defaults, or replace them with absolute paths."
            )
        for path in (
            self._settings.cognee_data_root_directory,
            self._settings.cognee_system_root_directory,
            self._settings.cognee_cache_root_directory,
        ):
            Path(path).mkdir(parents=True, exist_ok=True)
        os.environ["LLM_API_KEY"] = self._settings.llm_api_key
        os.environ["LLM_PROVIDER"] = self._settings.llm_provider
        os.environ["LLM_MODEL"] = self._settings.llm_model
        os.environ["DATA_ROOT_DIRECTORY"] = str(self._settings.cognee_data_root_directory)
        os.environ["SYSTEM_ROOT_DIRECTORY"] = str(self._settings.cognee_system_root_directory)
        os.environ["CACHE_ROOT_DIRECTORY"] = str(self._settings.cognee_cache_root_directory)

    def _ensure_client(self) -> Any:
        if self._cognee is not None:
            return self._cognee
        self._prepare_environment()
        try:
            import cognee
            from cognee import SearchType
        except ImportError as exc:
            raise CogneeUnavailableError("Cognee is not installed") from exc
        self._cognee = cognee
        self._search_type_chunks = SearchType.CHUNKS
        return self._cognee

    @staticmethod
    def dataset_name(project_id: str) -> str:
        return f"cortex_project_{project_id}"

    @staticmethod
    def serialize_memory_item(item: MemoryItem) -> str:
        payload = item.model_dump(mode="json")
        return "CORTEX_MEMORY_ITEM\n" + json.dumps(payload, sort_keys=True)

    @staticmethod
    def _extract_payload(candidate: Any) -> dict[str, Any] | None:
        if candidate is None:
            return None
        if isinstance(candidate, str):
            text = candidate
        elif isinstance(candidate, dict):
            for key in ("text", "content", "chunk", "raw_text"):
                if key in candidate and isinstance(candidate[key], str):
                    text = candidate[key]
                    break
            else:
                text = json.dumps(candidate, default=str)
        else:
            for attr in ("text", "content", "chunk", "raw_text"):
                value = getattr(candidate, attr, None)
                if isinstance(value, str):
                    text = value
                    break
            else:
                text = str(candidate)
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None

    async def store_memory_items(self, project_id: str, items: list[MemoryItem]) -> None:
        if not items:
            return
        cognee = self._ensure_client()
        dataset = self.dataset_name(project_id)
        documents = [self.serialize_memory_item(item) for item in items]
        logger.info(
            "storing memory items in cognee",
            extra={"project_id": project_id, "dataset": dataset, "count": len(items)},
        )
        try:
            await cognee.add(documents, dataset_name=dataset)
            await cognee.cognify(datasets=[dataset])
        except Exception as exc:  # pragma: no cover - exercised via API/service tests
            raise CogneeStorageError(f"Cognee storage failed: {exc}") from exc

    async def search_memory(self, project_id: str, query: str, top_k: int) -> list[dict[str, Any]]:
        cognee = self._ensure_client()
        dataset = self.dataset_name(project_id)
        logger.info(
            "searching cognee memory",
            extra={"project_id": project_id, "dataset": dataset, "query": query, "top_k": top_k},
        )
        try:
            raw_results = await cognee.search(
                query,
                query_type=self._search_type_chunks,
                datasets=[dataset],
                only_context=True,
                top_k=top_k,
            )
        except Exception as exc:  # pragma: no cover - exercised via API/service tests
            raise CogneeStorageError(f"Cognee search failed: {exc}") from exc
        payloads: list[dict[str, Any]] = []
        for result in raw_results:
            payload = self._extract_payload(result)
            if payload:
                payloads.append(payload)
        return payloads

    async def get_graph(self, project_id: str) -> list[dict[str, str]]:
        """Return knowledge-graph triples for a project via Cognee INSIGHTS search."""
        cognee = self._ensure_client()
        from cognee import SearchType

        dataset = self.dataset_name(project_id)
        logger.info("fetching graph triples", extra={"project_id": project_id, "dataset": dataset})
        try:
            raw = await cognee.search(
                "",
                query_type=SearchType.INSIGHTS,
                datasets=[dataset],
            )
        except Exception as exc:  # pragma: no cover
            raise CogneeStorageError(f"Cognee graph query failed: {exc}") from exc
        triples: list[dict[str, str]] = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                triples.append({"source": str(item[0]), "relation": str(item[1]), "target": str(item[2])})
            elif isinstance(item, dict):
                src = item.get("source") or item.get("subject") or item.get("from", "")
                rel = item.get("relation") or item.get("predicate") or item.get("type", "")
                tgt = item.get("target") or item.get("object") or item.get("to", "")
                if src and tgt:
                    triples.append({"source": str(src), "relation": str(rel), "target": str(tgt)})
        return triples
