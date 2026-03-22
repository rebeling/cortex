from __future__ import annotations


def test_chat_returns_grounded_answer_not_raw_context_dump(client, project_id: str) -> None:
    ingest = client.post(
        "/memory/ingest",
        json={
            "project_id": project_id,
            "source_type": "agent_summary",
            "content": "Authentication uses JWT tokens with RS256.",
            "file_paths": ["app/auth.py"],
            "metadata": {"source": "codex", "title": "Auth summary"},
        },
    )
    assert ingest.status_code == 200

    response = client.post(
        "/memory/chat",
        json={
            "project_id": project_id,
            "query": "How does authentication work?",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"]
    assert not payload["answer"].startswith("Relevant project memory:")
    assert "JWT" in payload["answer"]
    assert payload["answer_mode"] == "fallback"
    assert payload["supporting_items"]
    assert payload["supporting_items"][0]["dataset_id"] == project_id
    assert payload["supporting_items"][0]["dataset_name"] == f"cortex_project_{project_id}"


def test_chat_reports_missing_memory_cleanly(client, project_id: str) -> None:
    response = client.post(
        "/memory/chat",
        json={
            "project_id": project_id,
            "query": "What queue backend does this use?",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "I could not find relevant stored memory for that question."
    assert payload["answer_mode"] == "fallback"
    assert payload["supporting_items"] == []
