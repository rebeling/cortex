from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from app.models.project import ProjectModel, SessionModel


class ProjectRegistryService:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._path = base_dir / "registry.json"
        self._lock = Lock()
        self._base_dir.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write({"projects": {}, "sessions": {}, "fingerprints": {}})

    def _read(self) -> dict[str, Any]:
        with self._path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, payload: dict[str, Any]) -> None:
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

    def upsert_project(self, project: ProjectModel) -> None:
        with self._lock:
            payload = self._read()
            payload["projects"][project.id] = project.model_dump(mode="json")
            self._write(payload)

    def get_project(self, project_id: str) -> ProjectModel | None:
        with self._lock:
            payload = self._read()
        project = payload["projects"].get(project_id)
        return ProjectModel.model_validate(project) if project else None

    def get_project_by_repo_path(self, repo_path: Path | str) -> ProjectModel | None:
        resolved = str(Path(repo_path).resolve())
        with self._lock:
            payload = self._read()
        for project_payload in payload["projects"].values():
            if project_payload.get("repo_path") == resolved:
                return ProjectModel.model_validate(project_payload)
        return None

    def upsert_session(self, session: SessionModel) -> None:
        with self._lock:
            payload = self._read()
            payload["sessions"][session.id] = session.model_dump(mode="json")
            self._write(payload)

    def get_session(self, session_id: str) -> SessionModel | None:
        with self._lock:
            payload = self._read()
        session = payload["sessions"].get(session_id)
        return SessionModel.model_validate(session) if session else None

    def remember_fingerprint(self, project_id: str, fingerprint: str) -> None:
        with self._lock:
            payload = self._read()
            payload["fingerprints"].setdefault(project_id, [])
            if fingerprint not in payload["fingerprints"][project_id]:
                payload["fingerprints"][project_id].append(fingerprint)
            self._write(payload)

    def has_fingerprint(self, project_id: str, fingerprint: str) -> bool:
        with self._lock:
            payload = self._read()
        return fingerprint in payload["fingerprints"].get(project_id, [])
