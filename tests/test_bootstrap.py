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
    assert payload["memories_created"] == payload["stored_memory_count"]
    assert payload["files_scanned"] >= 1
    assert payload["files_imported"] is None
    assert ".cortex/project.yaml" in payload["created_files"]
    assert (repo_dir / ".cortex" / "project.yaml").exists()
    assert (repo_dir / ".cortex" / "brief.md").exists()
    assert (repo_dir / ".cortex" / "repo_map.json").exists()
    status_payload = json.loads((repo_dir / ".cortex" / "bootstrap_status.json").read_text(encoding="utf-8"))
    assert status_payload["bootstrap_complete"] is True
    assert status_payload["graph_dirty"] is False
    assert status_payload["last_graph_sync_at"]


def test_bootstrap_is_idempotent(client, repo_dir: Path) -> None:
    first = client.post("/projects/bootstrap", json={"repo_path": str(repo_dir)})
    second = client.post("/projects/bootstrap", json={"repo_path": str(repo_dir)})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["stored_memory_count"] == first.json()["stored_memory_count"]
    assert second.json()["memories_created"] == 0


def test_import_reports_imported_and_scanned_counts(client) -> None:
    files = [
        ("relative_paths", (None, "README.md")),
        ("files", ("README.md", b"# Demo\n\nFastAPI project\n", "text/markdown")),
        ("relative_paths", (None, "app/main.py")),
        ("files", ("app/main.py", b"from fastapi import FastAPI\napp = FastAPI()\n", "text/plain")),
        ("relative_paths", (None, "pyproject.toml")),
        ("files", ("pyproject.toml", b"[project]\nname='demo'\ndependencies=['fastapi']\n", "text/plain")),
    ]
    response = client.post("/projects/import", data={"folder_name": "demo"}, files=files)
    assert response.status_code == 200
    payload = response.json()
    assert payload["files_imported"] == 3
    assert payload["files_scanned"] == 3
    assert payload["memories_created"] == payload["stored_memory_count"]


def test_delete_project_removes_registry_entry(client, repo_dir: Path) -> None:
    bootstrap = client.post("/projects/bootstrap", json={"repo_path": str(repo_dir)})
    assert bootstrap.status_code == 200
    project_id = bootstrap.json()["project_id"]

    delete_response = client.delete(f"/projects/{project_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True}

    get_response = client.get(f"/projects/{project_id}")
    assert get_response.status_code == 404


def test_bootstrap_excludes_tests_directory(client, tmp_path: Path) -> None:
    repo = tmp_path / "repo_without_tests"
    repo.mkdir()
    (repo / "README.md").write_text("# Repo\n\nNo tests in import.\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='repo-without-tests'\n", encoding="utf-8")
    app_dir = repo / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_placeholder.py").write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")

    response = client.post("/projects/bootstrap", json={"repo_path": str(repo)})
    assert response.status_code == 200
    project_id = response.json()["project_id"]
    project_response = client.get(f"/projects/{project_id}")
    assert project_response.status_code == 200
    project = project_response.json()["project"]
    bootstrap_status = project_response.json()["bootstrap_status"]

    assert "tests" not in project.get("frameworks", [])
    assert bootstrap_status["stored_memory_count"] >= 1
    repo_map = (repo / ".cortex" / "repo_map.json").read_text(encoding="utf-8")
    assert "tests/test_placeholder.py" not in repo_map


def test_bootstrap_creates_file_level_memories_and_updates_hashes(client, tmp_path: Path) -> None:
    repo = tmp_path / "tracked_repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Repo\n\nBootstrap file memory test.\n", encoding="utf-8")
    app_dir = repo / "app"
    app_dir.mkdir()
    main_path = app_dir / "main.py"
    main_path.write_text("sentinel_v1 = 'alpha-file-memory'\n", encoding="utf-8")

    first = client.post("/projects/bootstrap", json={"repo_path": str(repo)})
    assert first.status_code == 200
    project_id = first.json()["project_id"]

    first_search = client.post(
        "/memory/search",
        json={"project_id": project_id, "query": "sentinel_v1", "top_k": 5},
    )
    assert first_search.status_code == 200
    first_titles = {item["item"]["title"] for item in first_search.json()["results"]}
    assert "app/main.py" in first_titles

    first_index = client.app.state.registry_service.get_file_memory_index(project_id)
    assert first_index["app/main.py"]["memory_id"]
    first_hash = first_index["app/main.py"]["source_hash"]

    main_path.write_text("sentinel_v2 = 'beta-file-memory'\n", encoding="utf-8")
    second = client.post("/projects/bootstrap", json={"repo_path": str(repo)})
    assert second.status_code == 200

    second_index = client.app.state.registry_service.get_file_memory_index(project_id)
    assert second_index["app/main.py"]["source_hash"] != first_hash
    assert second.json()["stored_memory_count"] == first.json()["stored_memory_count"]
    assert second.json()["memories_created"] >= 1

    second_search = client.post(
        "/memory/search",
        json={"project_id": project_id, "query": "sentinel_v2", "top_k": 5},
    )
    assert second_search.status_code == 200
    second_titles = {item["item"]["title"] for item in second_search.json()["results"]}
    assert "app/main.py" in second_titles

    old_search = client.post(
        "/memory/search",
        json={"project_id": project_id, "query": "sentinel_v1", "top_k": 5},
    )
    assert old_search.status_code == 200
    old_titles = {item["item"]["title"] for item in old_search.json()["results"]}
    assert "app/main.py" not in old_titles


def test_bootstrap_removes_deleted_file_memories_from_active_results(client, tmp_path: Path) -> None:
    repo = tmp_path / "delete_repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Repo\n\nDelete test.\n", encoding="utf-8")
    app_dir = repo / "app"
    app_dir.mkdir()
    deleted_path = app_dir / "obsolete.py"
    deleted_path.write_text("sentinel_deleted = 'gamma-file-memory'\n", encoding="utf-8")

    bootstrap = client.post("/projects/bootstrap", json={"repo_path": str(repo)})
    assert bootstrap.status_code == 200
    project_id = bootstrap.json()["project_id"]

    deleted_path.unlink()
    rebootstrap = client.post("/projects/bootstrap", json={"repo_path": str(repo)})
    assert rebootstrap.status_code == 200

    file_index = client.app.state.registry_service.get_file_memory_index(project_id)
    assert "app/obsolete.py" not in file_index
    assert rebootstrap.json()["stored_memory_count"] == bootstrap.json()["stored_memory_count"] - 1

    search = client.post(
        "/memory/search",
        json={"project_id": project_id, "query": "sentinel_deleted", "top_k": 5},
    )
    assert search.status_code == 200
    titles = {item["item"]["title"] for item in search.json()["results"]}
    assert "app/obsolete.py" not in titles


def test_reimport_project_preserves_project_id_and_updates_file_memories(client) -> None:
    initial_files = [
        ("relative_paths", (None, "README.md")),
        ("files", ("README.md", b"# Demo\n\nInitial import.\n", "text/markdown")),
        ("relative_paths", (None, "app/main.py")),
        ("files", ("app/main.py", b"sentinel_initial = 'first'\n", "text/plain")),
    ]
    create_response = client.post("/projects/import", data={"folder_name": "demo"}, files=initial_files)
    assert create_response.status_code == 200
    project_id = create_response.json()["project_id"]

    reimport_files = [
        ("relative_paths", (None, "README.md")),
        ("files", ("README.md", b"# Demo\n\nUpdated import.\n", "text/markdown")),
        ("relative_paths", (None, "app/main.py")),
        ("files", ("app/main.py", b"sentinel_updated = 'second'\n", "text/plain")),
    ]
    reimport_response = client.post(f"/projects/{project_id}/import", data={"folder_name": "demo"}, files=reimport_files)
    assert reimport_response.status_code == 200
    assert reimport_response.json()["project_id"] == project_id
    assert reimport_response.json()["files_imported"] == 2

    updated_search = client.post(
        "/memory/search",
        json={"project_id": project_id, "query": "sentinel_updated", "top_k": 5},
    )
    assert updated_search.status_code == 200
    updated_titles = {item["item"]["title"] for item in updated_search.json()["results"]}
    assert "app/main.py" in updated_titles

    stale_search = client.post(
        "/memory/search",
        json={"project_id": project_id, "query": "sentinel_initial", "top_k": 5},
    )
    assert stale_search.status_code == 200
    stale_titles = {item["item"]["title"] for item in stale_search.json()["results"]}
    assert "app/main.py" not in stale_titles


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
