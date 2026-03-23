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

    def _prepare_environment(self, project_id: str) -> None:
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

        # Project-specific Cognee directories for true multi-project isolation
        cognee_base = self._settings.service_data_dir / "cognee" / project_id
        data_dir = cognee_base / "data"
        system_dir = cognee_base / "system"
        cache_dir = cognee_base / "cache"

        for path in (data_dir, system_dir, cache_dir):
            path.mkdir(parents=True, exist_ok=True)

        os.environ["LLM_API_KEY"] = self._settings.llm_api_key
        os.environ["LLM_PROVIDER"] = self._settings.llm_provider
        os.environ["LLM_MODEL"] = self._settings.llm_model
        os.environ["DATA_ROOT_DIRECTORY"] = str(data_dir)
        os.environ["SYSTEM_ROOT_DIRECTORY"] = str(system_dir)
        os.environ["CACHE_ROOT_DIRECTORY"] = str(cache_dir)

    def _ensure_client(self, project_id: str) -> Any:
        # Always re-prepare environment to ensure correct project-specific directories
        self._prepare_environment(project_id)

        if self._cognee is not None:
            return self._cognee
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
        metadata: dict[str, Any] = {}
        candidate_texts: list[str] = []
        if candidate is None:
            return None
        if isinstance(candidate, str):
            candidate_texts.append(candidate)
        elif isinstance(candidate, dict):
            for key in ("dataset_id", "dataset_name", "dataset_tenant_id"):
                if key in candidate:
                    metadata[key] = candidate[key]
            for key in ("search_result", "text", "content", "chunk", "raw_text"):
                if key in candidate and isinstance(candidate[key], str):
                    candidate_texts.append(candidate[key])
            candidate_texts.append(json.dumps(candidate, default=str))
        else:
            for attr in ("dataset_id", "dataset_name", "dataset_tenant_id"):
                value = getattr(candidate, attr, None)
                if value is not None:
                    metadata[attr] = value
            for attr in ("search_result", "text", "content", "chunk", "raw_text"):
                value = getattr(candidate, attr, None)
                if isinstance(value, str):
                    candidate_texts.append(value)
            candidate_texts.append(str(candidate))
        for text in candidate_texts:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                continue
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                payload.update(metadata)
            return payload
        return None

    async def store_memory_items(self, project_id: str, items: list[MemoryItem], *, rebuild_graph: bool = True) -> None:
        if not items:
            return
        cognee = self._ensure_client(project_id)
        dataset = self.dataset_name(project_id)
        documents = [self.serialize_memory_item(item) for item in items]
        logger.info(
            "storing memory items in cognee",
            extra={"project_id": project_id, "dataset": dataset, "count": len(items)},
        )
        try:
            await cognee.add(documents, dataset_name=dataset)
        except Exception as exc:  # pragma: no cover - exercised via API/service tests
            raise CogneeStorageError(f"Cognee storage failed: {exc}") from exc
        if rebuild_graph:
            await self.sync_graph(project_id)

    async def sync_graph(self, project_id: str) -> None:
        cognee = self._ensure_client(project_id)
        dataset = self.dataset_name(project_id)
        logger.info("syncing graph", extra={"project_id": project_id, "dataset": dataset})
        try:
            await cognee.cognify(datasets=[dataset])
        except Exception as exc:  # pragma: no cover - exercised via API/service tests
            raise CogneeStorageError(f"Cognee graph sync failed: {exc}") from exc

    async def generate_graph_visualization(self, project_id: str, output_path: Path | str) -> Path:
        self._ensure_client(project_id)
        dataset = self.dataset_name(project_id)
        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "generating graph visualization",
            extra={"project_id": project_id, "dataset": dataset, "output_path": str(path)},
        )
        try:
            from cognee.api.v1.visualize.visualize import visualize_graph

            await visualize_graph(str(path))
        except Exception as exc:  # pragma: no cover - exercised via API/service tests
            raise CogneeStorageError(f"Cognee graph visualization failed: {exc}") from exc
        return path

    async def search_memory(self, project_id: str, query: str, top_k: int) -> list[dict[str, Any]]:
        cognee = self._ensure_client(project_id)
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
        """Return knowledge-graph triples for a project."""
        self._ensure_client(project_id)
        dataset = self.dataset_name(project_id)
        logger.info("fetching graph triples", extra={"project_id": project_id, "dataset": dataset})

        try:
            import cognee.infrastructure.databases.graph as g
            engine = await g.get_graph_engine()
            # In KuzuDB adapter for Cognee, get_graph_data() typically returns (nodes, edges) where edges are dicts
            data = await engine.get_graph_data()
        except Exception as exc:  # pragma: no cover
            raise CogneeStorageError(f"Cognee graph query failed: {exc}") from exc

        # Unpack edges from data
        # We expect data to be either a list of edges, or a tuple (nodes, edges)
        edges = []
        if isinstance(data, tuple) and len(data) == 2:
            edges = data[1]
        elif isinstance(data, list):
            edges = data

        logger.info("graph raw results", extra={"count": len(edges)})

        triples: list[dict[str, str]] = []
        for item in edges:
            if isinstance(item, dict):
                src = item.get("source_node_id") or item.get("source") or item.get("from") or ""
                rel = item.get("relationship_name") or item.get("relation") or item.get("type") or ""
                tgt = item.get("target_node_id") or item.get("target") or item.get("to") or ""
                if src and tgt:
                    triples.append({"source": str(src), "relation": str(rel), "target": str(tgt)})
            elif hasattr(item, "__dict__"):
                src = getattr(item, "source_node_id", None) or getattr(item, "source", None)
                rel = getattr(item, "relationship_name", None) or getattr(item, "relation", None)
                tgt = getattr(item, "target_node_id", None) or getattr(item, "target", None)
                if src and tgt:
                    triples.append({"source": str(src), "relation": str(rel), "target": str(tgt)})

        # Filter out node nodes pointing to themselves or noisy technical nodes if needed
        logger.info("graph parsed triples", extra={"count": len(triples)})
        return triples
