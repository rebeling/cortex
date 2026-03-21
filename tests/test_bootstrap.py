from __future__ import annotations

import json
from pathlib import Path
import os

from fastapi.testclient import TestClient
import yaml

from app.core.config import Settings
from app.main import create_app
from app.services.cognee_service import CogneeService, CogneeUnavailableError
from conftest import FailingCogneeService


def test_bootstrap_creates_cortex_files(client, repo_dir: Path) -> None:
    response = client.post("/projects/bootstrap", json={"repo_path": str(repo_dir)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["stored_memory_count"] >= 3
    assert ".cortex/project.yaml" in payload["created_files"]
    assert (repo_dir / ".cortex" / "project.yaml").exists()
    assert (repo_dir / ".cortex" / "brief.md").exists()
    assert (repo_dir / ".cortex" / "repo_map.json").exists()
    status_payload = json.loads((repo_dir / ".cortex" / "bootstrap_status.json").read_text(encoding="utf-8"))
    assert status_payload["bootstrap_complete"] is True


def test_bootstrap_is_idempotent(client, repo_dir: Path) -> None:
    first = client.post("/projects/bootstrap", json={"repo_path": str(repo_dir)})
    second = client.post("/projects/bootstrap", json={"repo_path": str(repo_dir)})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["stored_memory_count"] == 0


def test_bootstrap_persists_project_metadata_even_when_cognee_store_fails(tmp_path: Path, repo_dir: Path) -> None:
    settings = Settings(service_data_dir=tmp_path / ".cortex-service")
    client = TestClient(create_app(settings=settings, cognee_service=FailingCogneeService()))
    response = client.post("/projects/bootstrap", json={"repo_path": str(repo_dir)})
    assert response.status_code == 500
    project_payload = yaml.safe_load((repo_dir / ".cortex" / "project.yaml").read_text(encoding="utf-8"))
    project_id = project_payload["id"]
    get_response = client.get(f"/projects/{project_id}")
    assert get_response.status_code == 200
    status_payload = get_response.json()["bootstrap_status"]
    assert status_payload["bootstrap_complete"] is False
    assert status_payload["warnings"]


def test_framework_detection_avoids_readme_false_positives(client, tmp_path: Path) -> None:
    repo = tmp_path / "framework_repo"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# App\n\nThis project compares FastAPI with Express and Next.js, but uses FastAPI and Jinja only.\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text(
        "[project]\nname='app'\ndependencies=['fastapi','jinja2']\n",
        encoding="utf-8",
    )
    app_dir = repo / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text(
        "from fastapi import FastAPI\nfrom jinja2 import Environment\napp = FastAPI()\n",
        encoding="utf-8",
    )
    response = client.post("/projects/bootstrap", json={"repo_path": str(repo)})
    assert response.status_code == 200
    project_id = response.json()["project_id"]
    project_response = client.get(f"/projects/{project_id}")
    assert project_response.status_code == 200
    frameworks = project_response.json()["project"]["frameworks"]
    assert "FastAPI" in frameworks
    assert "Jinja" in frameworks
    assert "Express" not in frameworks
    assert "Next.js" not in frameworks


def test_bootstrap_requires_llm_api_key_for_default_cognee_service(tmp_path: Path, repo_dir: Path) -> None:
    settings = Settings(service_data_dir=tmp_path / ".cortex-service", llm_api_key="")
    client = TestClient(create_app(settings=settings))
    response = client.post("/projects/bootstrap", json={"repo_path": str(repo_dir)})
    assert response.status_code == 500
    assert "LLM_API_KEY is not configured" in response.json()["detail"]


def test_cognee_service_normalizes_relative_env_paths(tmp_path: Path) -> None:
    settings = Settings(
        llm_api_key="test-key",
        cognee_data_root_directory=tmp_path / "data",
        cognee_system_root_directory=tmp_path / "system",
        cognee_cache_root_directory=tmp_path / "cache",
    )
    service = CogneeService(settings)
    service._prepare_environment()
    assert settings.cognee_data_root_directory.is_absolute()
    assert settings.cognee_system_root_directory.is_absolute()
    assert settings.cognee_cache_root_directory.is_absolute()
    assert os.environ["DATA_ROOT_DIRECTORY"] == str(settings.cognee_data_root_directory)
    assert os.environ["SYSTEM_ROOT_DIRECTORY"] == str(settings.cognee_system_root_directory)
    assert os.environ["CACHE_ROOT_DIRECTORY"] == str(settings.cognee_cache_root_directory)


def test_cognee_service_rejects_relative_path_vars_in_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_ROOT_DIRECTORY", ".cognee/data")
    settings = Settings(
        llm_api_key="test-key",
        cognee_data_root_directory=tmp_path / "data",
        cognee_system_root_directory=tmp_path / "system",
        cognee_cache_root_directory=tmp_path / "cache",
    )
    service = CogneeService(settings)
    try:
        service._prepare_environment()
    except CogneeUnavailableError as exc:
        assert "must be absolute or omitted" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected CogneeUnavailableError for relative Cognee path vars")
