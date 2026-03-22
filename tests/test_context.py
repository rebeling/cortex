from __future__ import annotations


def test_context_returns_prompt_ready_memory_block(client, project_id: str) -> None:
    ingest = client.post(
        "/memory/ingest",
        json={
            "project_id": project_id,
            "source_type": "agent_summary",
            "content": {
                "summary": "Bootstrap creates .cortex metadata files and stores semantic memory in Cognee.",
                "details": ["FastAPI serves the endpoints", "Context responses stay compact"],
            },
            "file_paths": ["app/api/routes/projects.py", "app/services/context_service.py"],
            "metadata": {"source": "codex", "title": "Cortex memory context"},
        },
    )
    assert ingest.status_code == 200
    response = client.post(
        "/memory/context",
        json={
            "project_id": project_id,
            "query": "How does Cortex build prompt memory context?",
            "file_paths": ["app/services/context_service.py"],
            "top_k": 3,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["memory_block"].startswith("Relevant project memory:")
    assert payload["supporting_items"]
    assert payload["supporting_items"][0]["dataset_id"] == project_id
    assert payload["supporting_items"][0]["dataset_name"] == f"cortex_project_{project_id}"
