from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ProjectModel(BaseModel):
    id: str
    name: str
    repo_path: str
    canonical_identity: str
    created_at: datetime
    updated_at: datetime
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    bootstrap_complete: bool


class SessionModel(BaseModel):
    id: str
    project_id: str
    started_at: datetime
    ended_at: datetime | None = None
    source: str


class BootstrapRequest(BaseModel):
    repo_path: str
    project_name: str | None = None

    @field_validator("repo_path")
    @classmethod
    def validate_repo_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("repo_path must not be empty")
        return value


class BootstrapResponse(BaseModel):
    project_id: str
    created_files: list[str]
    bootstrap_summary: str
    stored_memory_count: int


class ProjectResponse(BaseModel):
    project: ProjectModel
    bootstrap_status: dict[str, object]
    cortex_files: dict[str, bool]
