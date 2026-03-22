from __future__ import annotations


def test_search_exposes_cognee_dataset_metadata(client, project_id: str) -> None:
    ingest = client.post(
        "/memory/ingest",
        json={
            "project_id": project_id,
            "source_type": "agent_summary",
            "content": "Cortex stores retrieval results in Cognee and ranks them by query overlap.",
            "file_paths": ["app/services/retrieval_service.py"],
            "metadata": {"source": "codex", "title": "Search summary"},
        },
    )
    assert ingest.status_code == 200

    response = client.post(
        "/memory/search",
        json={
            "project_id": project_id,
            "query": "How are retrieval results ranked?",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]
    first = payload["results"][0]
    assert first["dataset_id"] == project_id
    assert first["dataset_name"] == f"cortex_project_{project_id}"
    assert "search_result" not in first
