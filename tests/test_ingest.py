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
