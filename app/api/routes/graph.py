from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.services.cognee_service import CogneeStorageError, CogneeUnavailableError
from app.services.memory_service import ProjectNotFoundError

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/{project_id}")
async def get_graph(project_id: str, request: Request) -> dict:
    project = request.app.state.registry_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    try:
        triples = await request.app.state.cognee_service.get_graph(project_id)
    except (CogneeUnavailableError, CogneeStorageError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    node_set: set[str] = set()
    nodes: list[dict] = []
    edges: list[dict] = []
    for triple in triples:
        for label in (triple["source"], triple["target"]):
            if label not in node_set:
                node_set.add(label)
                nodes.append({"id": label, "label": label})
        edges.append({"from": triple["source"], "to": triple["target"], "label": triple["relation"]})
    return {"nodes": nodes, "edges": edges}
