from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.memory import MemoryItem
from app.services.cognee_service import CogneeStorageError


class FakeCogneeService:
    def __init__(self) -> None:
        self.items_by_project: dict[str, list[MemoryItem]] = {}
        self.rebuild_requests: list[tuple[str, bool]] = []
        self.sync_requests: list[str] = []
        self.visualization_requests: list[tuple[str, str]] = []

    async def store_memory_items(self, project_id: str, items: list[MemoryItem], *, rebuild_graph: bool = True) -> None:
        self.items_by_project.setdefault(project_id, [])
        self.items_by_project[project_id].extend(items)
        self.rebuild_requests.append((project_id, rebuild_graph))

    async def search_memory(self, project_id: str, query: str, top_k: int) -> list[dict]:
        query_tokens = {token for token in query.lower().split() if token}
        ranked = []
        for item in self.items_by_project.get(project_id, []):
            haystack = f"{item.title} {item.content}".lower()
            overlap = len(query_tokens.intersection(haystack.split()))
            if overlap or not query_tokens:
                ranked.append((overlap, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {
                "dataset_id": project_id,
                "dataset_name": f"cortex_project_{project_id}",
                "dataset_tenant_id": None,
                "search_result": "CORTEX_MEMORY_ITEM\n" + json.dumps(item.model_dump(mode="json"), sort_keys=True),
            }
            for _, item in ranked[:top_k]
        ]

    async def sync_graph(self, project_id: str) -> None:
        self.sync_requests.append(project_id)

    async def generate_graph_visualization(self, project_id: str, output_path: Path | str) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"<html><body><h1>Graph for {project_id}</h1></body></html>",
            encoding="utf-8",
        )
        self.visualization_requests.append((project_id, str(path)))
        return path


class FailingCogneeService(FakeCogneeService):
    async def store_memory_items(self, project_id: str, items: list[MemoryItem], *, rebuild_graph: bool = True) -> None:
        raise CogneeStorageError("simulated cognee failure")


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Sample Repo\n\nFastAPI service for project memory.\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'sample-repo'\ndependencies = ['fastapi', 'pydantic']\n",
        encoding="utf-8",
    )
    app_dir = repo / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_placeholder.py").write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    return repo


@pytest.fixture
def app(tmp_path: Path):
    settings = Settings(service_data_dir=tmp_path / ".cortex-service", llm_api_key="")
    return create_app(settings=settings, cognee_service=FakeCogneeService())


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def project_id(client: TestClient, repo_dir: Path) -> str:
    response = client.post("/projects/bootstrap", json={"repo_path": str(repo_dir)})
    assert response.status_code == 200
    return response.json()["project_id"]
