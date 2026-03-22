from __future__ import annotations


def test_root_renders_template_ui(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Cortex - Memory Explorer" in response.text
    assert 'extends "base.html"' not in response.text
    assert "cortex.selectedProjectId" in response.text


def test_graph_visualization_syncs_before_serving_missing_artifact(client, project_id: str) -> None:
    response = client.get(f"/graph/{project_id}/visualization")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Graph for" in response.text
    assert client.app.state.cognee_service.sync_requests[-1] == project_id
