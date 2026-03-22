from __future__ import annotations


def test_ingest_creates_implicit_session_and_stores_memory(client, project_id: str) -> None:
    response = client.post(
        "/memory/ingest",
        json={
            "project_id": project_id,
            "source_type": "agent_summary",
            "content": "Cortex uses FastAPI for the API layer. The bootstrap flow stores facts and descriptions in Cognee.",
            "file_paths": ["app/main.py", "app/services/bootstrap_service.py"],
            "metadata": {"source": "codex"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert len(payload["stored_items"]) >= 2
    assert {item["type"] for item in payload["stored_items"]}.issubset({"fact", "description"})


def test_ingest_blocks_obvious_duplicates(client, project_id: str) -> None:
    body = {
        "project_id": project_id,
        "source_type": "agent_summary",
        "content": "Cortex uses FastAPI for the API layer.",
        "file_paths": ["app/main.py"],
        "metadata": {"source": "codex"},
    }
    first = client.post("/memory/ingest", json=body)
    second = client.post("/memory/ingest", json=body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(second.json()["stored_items"]) == 0


def test_ingest_skips_graph_rebuild_and_marks_graph_outdated(client, project_id: str) -> None:
    response = client.post(
        "/memory/ingest",
        json={
            "project_id": project_id,
            "source_type": "agent_summary",
            "content": "Cortex stores pushed memory without rebuilding the graph immediately.",
            "file_paths": ["app/main.py"],
            "metadata": {"source": "frontend"},
        },
    )

    assert response.status_code == 200
    assert client.app.state.cognee_service.rebuild_requests[-1] == (project_id, False)

    project_response = client.get(f"/projects/{project_id}")
    assert project_response.status_code == 200
    payload = project_response.json()
    assert payload["project"]["graph_dirty"] is True
    assert payload["bootstrap_status"]["graph_dirty"] is True


def test_search_syncs_dirty_graph_before_retrieval(client, project_id: str) -> None:
    ingest = client.post(
        "/memory/ingest",
        json={
            "project_id": project_id,
            "source_type": "agent_summary",
            "content": "Authentication uses JWT tokens with RS256.",
            "file_paths": ["app/auth.py"],
            "metadata": {"source": "frontend"},
        },
    )
    assert ingest.status_code == 200

    search = client.post(
        "/memory/search",
        json={
            "project_id": project_id,
            "query": "How does authentication work?",
            "top_k": 3,
        },
    )
    assert search.status_code == 200
    assert search.json()["results"]
    assert client.app.state.cognee_service.sync_requests[-1] == project_id

    project_response = client.get(f"/projects/{project_id}")
    assert project_response.status_code == 200
    payload = project_response.json()
    assert payload["project"]["graph_dirty"] is False
    assert payload["bootstrap_status"]["graph_dirty"] is False
